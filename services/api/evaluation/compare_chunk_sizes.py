"""Compare JD semantic chunk sizes on one frozen CareerPilot corpus.

The benchmark is intentionally isolated from PostgreSQL.  It rebuilds chunks
and Qwen vectors in memory for every configuration, holds the corpus, labels,
embedding model, retrieval parameters and query set fixed, and never mutates
the production knowledge index.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np

from app.llm.tokenization import CallableTokenCounter
from app.models.entities import Job
from app.services.job_knowledge import (
    JOB_KNOWLEDGE_CHUNKING_VERSION,
    JobKnowledgeChunkingConfig,
    build_job_knowledge_chunks,
)
from evaluation.compare_embeddings import (
    DEFAULT_DENSE_TOP_K,
    DEFAULT_SPARSE_TOP_K,
    QWEN_MODEL,
    SparseIndex,
    encode_documents,
    encode_sentence_transformer,
    load_sentence_transformer,
    reciprocal_rank_fusion,
    top_indices,
)
from evaluation.metrics import retrieval_metrics, validate_labels

METRIC_TOP_K = 5
CONTEXT_CHUNK_LIMIT = 10


@dataclass(frozen=True)
class ChunkSpec:
    token_limit: int
    token_overlap: int = 0

    def __post_init__(self) -> None:
        JobKnowledgeChunkingConfig(
            token_limit=self.token_limit,
            token_overlap=self.token_overlap,
        )

    @property
    def name(self) -> str:
        return f"tokens-{self.token_limit}-overlap-{self.token_overlap}"


def _save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_specs(value: str) -> list[ChunkSpec]:
    specs: list[ChunkSpec] = []
    for raw in value.split(","):
        parts = raw.strip().split(":")
        if not parts[0]:
            continue
        spec = ChunkSpec(
            token_limit=int(parts[0]),
            token_overlap=int(parts[1]) if len(parts) > 1 else 0,
        )
        if spec not in specs:
            specs.append(spec)
    if not specs:
        raise ValueError("At least one chunk specification is required")
    return specs


def _job(data: dict[str, Any]) -> Job:
    return Job(
        id=UUID(data["id"]),
        platform=data.get("platform") or "evaluation",
        external_job_id=data.get("external_job_id"),
        title=data.get("title") or "未命名岗位",
        description=data.get("description") or "",
        location=data.get("location"),
        salary_min=data.get("salary_min"),
        salary_max=data.get("salary_max"),
        job_type=data.get("job_type"),
        education_requirement=data.get("education_requirement"),
        experience_requirement=data.get("experience_requirement"),
        source_url=data.get("source_url"),
        content_hash=data.get("content_hash")
        or hashlib.sha256((data.get("description") or "").encode()).hexdigest(),
        raw_data={},
        normalized_data={},
    )


def _chunks(
    jobs: list[dict[str, Any]],
    spec: ChunkSpec,
    counter: CallableTokenCounter,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    config = JobKnowledgeChunkingConfig(
        token_limit=spec.token_limit,
        token_overlap=spec.token_overlap,
    )
    for raw_job in jobs:
        job = _job(raw_job)
        for draft in build_job_knowledge_chunks(job, token_counter=counter, chunking=config):
            output.append(
                {
                    "job_id": str(job.id),
                    "section_type": draft.section_type,
                    "content": draft.content,
                    "embedding_content": draft.embedding_content,
                    "content_hash": draft.content_hash,
                    "token_count": draft.token_count,
                }
            )
    return output


def _ranked_indices(
    dense_scores: np.ndarray,
    sparse_scores: np.ndarray,
    mode: str,
) -> list[int]:
    dense = top_indices(dense_scores, DEFAULT_DENSE_TOP_K)
    if mode == "dense":
        return dense
    sparse = top_indices(sparse_scores, DEFAULT_SPARSE_TOP_K)
    return reciprocal_rank_fusion(dense, sparse)


def _job_ranking(ranked: list[int], chunks: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(chunks[index]["job_id"] for index in ranked))[:METRIC_TOP_K]


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int(len(ordered) * fraction) - 1))]


def _summary(rows: list[dict[str, Any]], chunk_stats: dict[str, dict]) -> list[dict]:
    output = []
    keys = list(dict.fromkeys((row["config"], row["mode"], row["split"]) for row in rows))
    for config, mode, split in keys:
        group = [
            row
            for row in rows
            if row["config"] == config and row["mode"] == mode and row["split"] == split
        ]
        answerable = [row for row in group if row["relevant_count"]]
        unanswerable = [row for row in group if not row["relevant_count"]]
        stats = chunk_stats[config]
        output.append(
            {
                "config": config,
                "mode": mode,
                "split": split,
                "answerable": len(answerable),
                "unanswerable": len(unanswerable),
                **{
                    metric: statistics.mean(row["metrics"][metric] for row in answerable)
                    if answerable
                    else None
                    for metric in ("precision", "recall", "hit_rate", "ndcg", "mrr")
                },
                "p50_query_ms": statistics.median(row["latency_ms"] for row in group),
                "p95_query_ms": _percentile([row["latency_ms"] for row in group], 0.95),
                "mean_context_tokens": statistics.mean(row["context_tokens"] for row in group),
                "p95_context_tokens": _percentile([row["context_tokens"] for row in group], 0.95),
                "unanswerable_return_rate": (
                    statistics.mean(float(row["metrics"]["returned_any"]) for row in unanswerable)
                    if unanswerable
                    else None
                ),
                **stats,
            }
        )
    return output


def _report(metadata: dict[str, Any]) -> str:
    lines = [
        "# CareerPilot JD Chunk Size 对比实验",
        "",
        (
            f"冻结语料：`{metadata['corpus_sha256']}`；{metadata['jobs']} 个岗位，"
            f"{metadata['cases']} 个问题；模型 `{metadata['embedding_model']}`。"
        ),
        "",
        "本实验为 silver 标签工程评测，未经过双人标注，不能作为人工金标准确率。",
        "各配置均重新切块并重新生成向量，生产知识库未被修改。",
        "",
        "|Chunk 配置|检索|集合|块数|平均块 Token|Recall@5|nDCG@5|MRR@5|"
        "平均上下文 Token|P95 查询 ms|",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in metadata["summary"]:
        lines.append(
            f"|{row['config']}|{row['mode']}|{row['split']}|{row['chunk_count']}|"
            f"{row['mean_chunk_tokens']:.1f}|{row['recall'] or 0:.3f}|"
            f"{row['ndcg'] or 0:.3f}|{row['mrr'] or 0:.3f}|"
            f"{row['mean_context_tokens']:.1f}|{row['p95_query_ms']:.1f}|"
        )
    best = metadata.get("best_test_hybrid")
    if best:
        lines.extend(
            [
                "",
                "## 本轮建议",
                "",
                (
                    f"测试集 Hybrid nDCG@5 最高的是 `{best['config']}` "
                    f"({best['ndcg']:.3f})；Recall@5={best['recall']:.3f}，"
                    f"平均上下文 {best['mean_context_tokens']:.1f} Token。"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本轮只评价 JD 知识检索，不评价简历匹配；"
            "简历 Chunk 需要单独的简历—岗位人工相关性标签。",
            "无答案问题未应用相关度阈值，因此仅记录返回率，不用它选择生产阈值。",
        ]
    )
    return "\n".join(lines) + "\n"


async def main(args: argparse.Namespace) -> None:
    started = time.perf_counter()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    corpus_path = Path(args.corpus).resolve()
    labels_path = Path(args.labels).resolve()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    corpus_hash = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    if labels.get("corpus_sha256") != corpus_hash:
        raise ValueError("Labels do not belong to this frozen corpus")
    questions = labels["questions"]
    validate_labels(questions, {job["id"] for job in corpus["jobs"]})
    specs = _parse_specs(args.configs)
    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    if not modes or any(mode not in {"dense", "hybrid"} for mode in modes):
        raise ValueError("modes must contain dense and/or hybrid")

    cache = os.getenv("SEMANTIC_CACHE_DIR") or str(Path("../../outputs/model-cache").resolve())
    model = load_sentence_transformer(QWEN_MODEL, cache)
    tokenizer = model.tokenizer
    counter = CallableTokenCounter(
        callback=lambda text: len(tokenizer.encode(text, add_special_tokens=False)),
        signature=f"huggingface:{QWEN_MODEL}",
        exact=True,
    )
    queries = list(dict.fromkeys(question["query"] for question in questions))
    query_hash = hashlib.sha256("\n".join(queries).encode()).hexdigest()[:12]
    query_vector_path = output / f"queries-{query_hash}-vectors.npy"
    if query_vector_path.exists():
        query_vectors = np.load(query_vector_path, allow_pickle=False)
        if query_vectors.shape[0] != len(queries):
            query_vectors = encode_sentence_transformer(model, queries, query=True)
            np.save(query_vector_path, query_vectors)
    else:
        query_vectors = encode_sentence_transformer(model, queries, query=True)
        np.save(query_vector_path, query_vectors)
    query_by_text = dict(zip(queries, query_vectors, strict=True))

    partial_path = output / "results.partial.json"
    rows: list[dict[str, Any]] = (
        json.loads(partial_path.read_text(encoding="utf-8")) if partial_path.exists() else []
    )
    chunk_stats: dict[str, dict] = {}
    expected_rows = len(questions) * len(modes)
    for spec in specs:
        chunks = _chunks(corpus["jobs"], spec, counter)
        documents = [chunk["embedding_content"] for chunk in chunks]
        chunk_hash = hashlib.sha256(
            "\n".join(chunk["content_hash"] for chunk in chunks).encode()
        ).hexdigest()
        vector_path = output / f"{spec.name}-{chunk_hash[:12]}-vectors.npy"
        encode_started = time.perf_counter()
        if vector_path.exists():
            document_vectors = np.load(vector_path, allow_pickle=False)
            cached = document_vectors.shape[0] == len(chunks)
        else:
            cached = False
            document_vectors = np.empty((0, 0), dtype=np.float32)
        if not cached:
            document_vectors = encode_documents(model, documents)
            np.save(vector_path, document_vectors)
        encode_ms = 0.0 if cached else (time.perf_counter() - encode_started) * 1000
        sparse = SparseIndex(documents)
        token_counts = [chunk["token_count"] for chunk in chunks]
        chunk_stats[spec.name] = {
            "chunk_count": len(chunks),
            "mean_chunk_tokens": statistics.mean(token_counts),
            "p95_chunk_tokens": _percentile([float(value) for value in token_counts], 0.95),
            "document_encode_ms": round(encode_ms, 2),
            "vectors_cached": cached,
        }
        existing_rows = [row for row in rows if row.get("config") == spec.name]
        if len(existing_rows) == expected_rows:
            print(f"reused {spec.name}: {len(chunks)} chunks", flush=True)
            continue
        rows = [row for row in rows if row.get("config") != spec.name]
        for question in questions:
            query_vector = query_by_text[question["query"]]
            query_started = time.perf_counter()
            dense_scores = document_vectors @ query_vector
            sparse_scores = sparse.score(question["query"])
            for mode in modes:
                ranked = _ranked_indices(dense_scores, sparse_scores, mode)
                job_ids = _job_ranking(ranked, chunks)
                relevant = [item["job_id"] for item in question["relevance"] if item["grade"] > 0]
                rows.append(
                    {
                        "config": spec.name,
                        "mode": mode,
                        "case_id": question["id"],
                        "split": question["split"],
                        "relevant_count": len(relevant),
                        "job_ids": job_ids,
                        "metrics": retrieval_metrics(job_ids, relevant, k=METRIC_TOP_K),
                        "context_tokens": sum(
                            chunks[index]["token_count"] for index in ranked[:CONTEXT_CHUNK_LIMIT]
                        ),
                        "latency_ms": round((time.perf_counter() - query_started) * 1000, 3),
                    }
                )
        _save(partial_path, rows)
        print(f"completed {spec.name}: {len(chunks)} chunks", flush=True)

    summary = _summary(rows, chunk_stats)
    test_hybrid = [
        item
        for item in summary
        if item["mode"] == "hybrid" and item["split"] == "test" and item["ndcg"] is not None
    ]
    best = (
        max(test_hybrid, key=lambda item: (item["ndcg"], item["recall"])) if test_hybrid else None
    )
    metadata = {
        "corpus_sha256": corpus_hash,
        "label_status": "silver_requires_human_review",
        "jobs": len(corpus["jobs"]),
        "cases": len(questions),
        "embedding_model": QWEN_MODEL,
        "chunking_version": JOB_KNOWLEDGE_CHUNKING_VERSION,
        "configs": [asdict(spec) for spec in specs],
        "retrieval": {
            "modes": modes,
            "metric_top_k_jobs": METRIC_TOP_K,
            "dense_top_k_chunks": DEFAULT_DENSE_TOP_K,
            "sparse_top_k_chunks": DEFAULT_SPARSE_TOP_K,
            "context_chunk_limit": CONTEXT_CHUNK_LIMIT,
        },
        "summary": summary,
        "best_test_hybrid": best,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "production_index_unchanged": True,
        "paid_llm_calls": 0,
    }
    _save(output / "results.json", rows)
    _save(output / "manifest.json", metadata)
    (output / "report.md").write_text(_report(metadata), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--output", default="../../outputs/evaluation-chunk-sizes-v1")
    parser.add_argument(
        "--configs",
        default="80:0,110:0,160:16,256:32,384:48",
        help="Comma-separated token_limit:token_overlap pairs",
    )
    parser.add_argument("--modes", default="dense,hybrid")
    asyncio.run(main(parser.parse_args()))
