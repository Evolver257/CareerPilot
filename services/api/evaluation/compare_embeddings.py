"""Compare embedding and retrieval strategies on one frozen job corpus.

Run from ``services/api``::

    python -m evaluation.compare_embeddings \
      --corpus ../../outputs/evaluation-v3-fixed-corpus/corpus.json \
      --labels ../../outputs/evaluation-v3-fixed-corpus/labels.json \
      --output ../../outputs/evaluation-embeddings-v1

The experiment is intentionally isolated from the production pgvector schema.
The current application index is 1024-dimensional, while Qwen3-Embedding and
BGE-M3 natively produce larger vectors. Reusing the production tables here
would either truncate vectors or mutate the live index, which would make the
comparison invalid and unsafe. The script reuses the production chunker to
create the exact same knowledge chunks, then ranks those chunks in memory.

The three requested candidates are:

* ``text-embedding-3-small`` through the OpenAI-compatible embeddings API;
* ``Qwen/Qwen3-Embedding-0.6B`` through Sentence Transformers;
* ``BAAI/bge-m3`` dense retrieval plus a BM25-style sparse retriever and
  ``BAAI/bge-reranker-v2-m3`` for the full hybrid stack.

Labels are deliberately called ``silver`` unless an external reviewed labels
file is supplied. This makes the numbers useful for engineering comparison,
but not suitable for claiming production accuracy.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import re
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import UUID

import httpx
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.llm.provider import MockLLMProvider
from app.models.base import Base
from app.models.entities import Job, JobKnowledgeChunk
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.services.job_knowledge import JOB_KNOWLEDGE_VERSION
from app.services.knowledge_indexing import KnowledgeIndexService
from evaluation.cases import cases
from evaluation.metrics import retrieval_metrics, validate_labels

QWEN_MODEL = "Qwen/Qwen3-Embedding-0.6B"
BGE_MODEL = "BAAI/bge-m3"
BGE_RERANKER = "BAAI/bge-reranker-v2-m3"
OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_RRF_K = 60
DEFAULT_DENSE_TOP_K = 100
DEFAULT_SPARSE_TOP_K = 100
DEFAULT_RERANK_POOL = 40


@dataclass(frozen=True)
class ExperimentSpec:
    name: str
    model: str
    strategy: str


SPECS = (
    ExperimentSpec("openai_text_embedding_3_small", OPENAI_MODEL, "dense"),
    ExperimentSpec("qwen3_embedding_0_6b", QWEN_MODEL, "dense"),
    ExperimentSpec("bge_m3_dense", BGE_MODEL, "dense"),
    ExperimentSpec("bge_m3_dense_sparse", BGE_MODEL, "hybrid"),
    ExperimentSpec("bge_m3_dense_sparse_rerank", BGE_MODEL, "hybrid_rerank"),
)


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _cjk_bigrams(text: str) -> list[str]:
    result: list[str] = []
    run: list[str] = []
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            run.append(char)
            continue
        if run:
            result.extend(run)
            result.extend("".join(run[i : i + 2]) for i in range(len(run) - 1))
            run = []
    if run:
        result.extend(run)
        result.extend("".join(run[i : i + 2]) for i in range(len(run) - 1))
    return result


def tokenize(text: str) -> list[str]:
    """Tokenize Chinese and technical terms for the experiment's sparse leg."""

    tokens = [part.lower() for part in re.findall(r"[A-Za-z0-9_+#./-]+", text)]
    tokens.extend(_cjk_bigrams(text))
    return tokens


class SparseIndex:
    """Small dependency-free BM25 index for a reproducible local baseline."""

    def __init__(self, documents: list[str], *, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents = [tokenize(document) for document in documents]
        self.lengths = np.asarray([len(document) for document in self.documents], dtype=np.float32)
        self.average_length = float(self.lengths.mean()) if len(self.lengths) else 1.0
        self.term_frequency = [Counter(document) for document in self.documents]
        document_frequency: Counter[str] = Counter()
        for terms in self.documents:
            document_frequency.update(set(terms))
        self.idf = {
            term: math.log(1 + (len(self.documents) - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def score(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.documents), dtype=np.float32)
        query_terms = set(tokenize(query))
        for term in query_terms:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for index, counts in enumerate(self.term_frequency):
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                length_ratio = self.lengths[index] / max(self.average_length, 1.0)
                denominator = frequency + self.k1 * (1 - self.b + self.b * length_ratio)
                scores[index] += idf * frequency * (self.k1 + 1) / denominator
        return scores


def top_indices(scores: np.ndarray, limit: int) -> list[int]:
    if len(scores) == 0:
        return []
    limit = min(limit, len(scores))
    if limit == len(scores):
        indices = np.arange(len(scores))
    else:
        indices = np.argpartition(-scores, limit - 1)[:limit]
    return sorted(
        (int(index) for index in indices),
        key=lambda index: float(scores[index]),
        reverse=True,
    )


def reciprocal_rank_fusion(*ranked_lists: list[int], constant: int = DEFAULT_RRF_K) -> list[int]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, index in enumerate(ranked, start=1):
            scores[index] = scores.get(index, 0.0) + 1.0 / (constant + rank)
    return sorted(scores, key=lambda index: scores[index], reverse=True)


def load_sentence_transformer(model_name: str, cache: str | None):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        model_name,
        device=os.getenv("EVAL_DEVICE", "cpu"),
        cache_folder=cache,
        trust_remote_code=False,
    )
    model.max_seq_length = int(os.getenv("EVAL_MAX_SEQ_LENGTH", "512"))
    return model


def encode_sentence_transformer(model, texts: list[str], *, query: bool = False) -> np.ndarray:
    kwargs = {
        "batch_size": int(os.getenv("EVAL_BATCH_SIZE", "16")),
        "normalize_embeddings": True,
        "show_progress_bar": False,
        "convert_to_numpy": True,
    }
    if query and getattr(model, "prompts", None) and "query" in model.prompts:
        kwargs["prompt_name"] = "query"
    return np.asarray(model.encode(texts, **kwargs), dtype=np.float32)


def encode_documents(model, documents: list[str]) -> np.ndarray:
    """Encode documents in checkpointed batches so long CPU runs are observable."""

    if isinstance(model, OpenAIEmbedder):
        return model.encode(documents)
    batch_size = int(os.getenv("EVAL_DOCUMENT_BATCHES", "64"))
    vectors = []
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        vectors.append(encode_sentence_transformer(model, batch))
        completed = min(start + batch_size, len(documents))
        if completed == len(documents) or completed % (batch_size * 4) == 0:
            print(f"encoded documents {completed}/{len(documents)}", flush=True)
    return np.concatenate(vectors, axis=0)


class OpenAIEmbedder:
    def __init__(self, model: str):
        self.model = model
        self.api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = (
            os.getenv("EMBEDDING_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY or EMBEDDING_API_KEY is not configured")
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "120")),
            trust_env=False,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        batch_size = int(os.getenv("OPENAI_EMBED_BATCH_SIZE", "64"))
        vectors: list[list[float] | None] = [None] * len(texts)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = self.client.post(
                "/embeddings",
                json={"input": batch, "model": self.model, "encoding_format": "float"},
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("data", []):
                vectors[start + int(item["index"])] = item["embedding"]
        if any(vector is None for vector in vectors):
            raise RuntimeError("OpenAI embeddings response did not contain every input")
        result = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(result, axis=1, keepdims=True)
        return result / np.maximum(norms, 1e-12)

    def close(self) -> None:
        self.client.close()


def rank_job_ids(
    chunk_job_ids: list[str],
    dense_scores: np.ndarray,
    sparse_scores: np.ndarray | None,
    rerank_scores: np.ndarray | None,
    *,
    dense_top_k: int,
    sparse_top_k: int,
    rerank_pool: int,
    strategy: str,
) -> list[str]:
    dense_ranked = top_indices(dense_scores, dense_top_k)
    if strategy == "dense":
        ranked = dense_ranked
    else:
        assert sparse_scores is not None
        sparse_ranked = top_indices(sparse_scores, sparse_top_k)
        ranked = reciprocal_rank_fusion(dense_ranked, sparse_ranked)
    if strategy == "hybrid_rerank":
        assert rerank_scores is not None
        candidate_indices = ranked[:rerank_pool]
        ranked = (
            sorted(
                candidate_indices,
                key=lambda index: float(rerank_scores[index]),
                reverse=True,
            )
            + ranked[rerank_pool:]
        )
    return list(dict.fromkeys(chunk_job_ids[index] for index in ranked))


def build_questions(
    snapshot: dict,
    labels_path: Path | None,
    corpus_hash: str,
) -> tuple[list[dict], str]:
    questions = cases()
    for question in questions:
        relevance = []
        for job in snapshot["jobs"]:
            content = job["title"] + "\n" + job["description"]
            match = re.search(question["criterion"], content, re.I)
            if match:
                relevance.append(
                    {
                        "job_id": job["id"],
                        "grade": 1,
                        "evidence": content[max(0, match.start() - 70) : match.end() + 100],
                    }
                )
        question["relevance"] = relevance
    label_status = "silver_requires_human_review"
    if labels_path:
        reviewed = json.loads(labels_path.read_text(encoding="utf-8"))
        if reviewed["corpus_sha256"] != corpus_hash:
            raise ValueError("Reviewed labels belong to a different corpus snapshot")
        questions = reviewed["questions"]
        label_status = (
            "silver_requires_human_review"
            if any("silver" in question.get("label_status", "") for question in questions)
            else "external_labels_supplied"
        )
    validate_labels(questions, {job["id"] for job in snapshot["jobs"]})
    return questions, label_status


async def load_chunks(snapshot: dict) -> list[dict]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for data in snapshot["jobs"]:
            values = {**data, "id": UUID(data["id"]), "raw_data": {}, "normalized_data": {}}
            session.add(Job(**values))
        await session.commit()
        mock = MockLLMProvider()
        index = KnowledgeIndexService(session, mock)
        run = await index.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
        run = await index.execute(run.id, mock)
        if run.status != "SUCCEEDED":
            raise RuntimeError(f"Fixture indexing failed: {run.error}")
        chunks = list(
            (
                await session.scalars(
                    select(JobKnowledgeChunk).order_by(
                        JobKnowledgeChunk.job_id,
                        JobKnowledgeChunk.section_type,
                        JobKnowledgeChunk.content_hash,
                    )
                )
            ).all()
        )
        # Keep ORM objects usable after the session closes; only these fields are consumed.
        detached = []
        for chunk in chunks:
            embedding_context = str(
                (chunk.chunk_metadata or {}).get("embedding_context") or ""
            ).strip()
            detached.append(
                {
                    "job_id": str(chunk.job_id),
                    "content": (
                        f"{embedding_context}\n{chunk.content}".strip()
                        if embedding_context
                        else chunk.content
                    ),
                    "content_hash": chunk.content_hash,
                    "section_type": chunk.section_type,
                }
            )
    await engine.dispose()
    return detached


def reranker_model(model_name: str, cache: str | None):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(
        model_name,
        device=os.getenv("EVAL_DEVICE", "cpu"),
        cache_folder=cache,
        trust_remote_code=False,
    )


def encode_rerank(model, query: str, documents: list[str]) -> np.ndarray:
    if not documents:
        return np.asarray([], dtype=np.float32)
    values = model.predict(
        [(query, document) for document in documents],
        batch_size=int(os.getenv("EVAL_RERANK_BATCH_SIZE", "16")),
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return np.asarray(values, dtype=np.float32)


def calculate_summary(results: list[dict], names: list[str]) -> list[dict]:
    summaries = []
    for name in names:
        for split in ("dev", "test"):
            group = [item for item in results if item["model"] == name and item["split"] == split]
            labeled = [item for item in group if item["relevant_count"]]
            empty = [item for item in group if not item["relevant_count"]]
            if not group:
                continue
            summaries.append(
                {
                    "model": name,
                    "split": split,
                    "answerable": len(labeled),
                    "unanswerable": len(empty),
                    **{
                        metric: statistics.mean(item["metrics"][metric] for item in labeled)
                        if labeled
                        else None
                        for metric in ("recall", "ndcg", "mrr")
                    },
                    "p50_ms": statistics.median(item["latency_ms"] for item in group),
                    "p95_ms": sorted(item["latency_ms"] for item in group)[
                        max(0, int(len(group) * 0.95) - 1)
                    ],
                    "unanswerable_return_rate": (
                        sum(item["metrics"]["returned_any"] for item in empty) / len(empty)
                        if empty
                        else None
                    ),
                }
            )
    return summaries


def markdown_report(metadata: dict) -> str:
    lines = [
        "# CareerPilot Embedding / Retrieval 对比实验",
        "",
        (
            f"数据快照：`{metadata['corpus_sha256']}`；{metadata['jobs']} 个岗位，"
            f"{metadata['chunks']} 个知识块，{metadata['cases']} 个问题。"
        ),
        "",
        "## 结论边界",
        "",
        "本实验复用生产切块器，但在内存中独立完成向量与检索，未写入线上 1024 维索引。",
        (
            "相关性标签是预先声明规则生成的 silver 标注，除非 manifest 标记为 "
            "external_labels_supplied，否则不能视为人工金标准。"
        ),
        (
            "BGE 的 sparse leg 使用依赖无关的 BM25-style 稀疏检索，BGE-M3 的 dense 向量 "
            "与 BGE reranker 单独计时。"
        ),
        "延迟为本机预热后的 CPU/指定设备查询延迟，不包含模型下载和生成式回答。",
        "Recall@5、nDCG@5、MRR@5 都按去重后的岗位计算；无相关问题只统计返回候选比例。",
        "",
        "## 汇总",
        "",
        "|方案|集合|有答案|Recall@5|nDCG@5|MRR@5|P50 ms|P95 ms|无答案仍返回|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in metadata["summary"]:
        lines.append(
            f"|{item['model']}|{item['split']}|{item['answerable']}|"
            f"{item['recall'] or 0:.3f}|{item['ndcg'] or 0:.3f}|{item['mrr'] or 0:.3f}|"
            f"{item['p50_ms']:.1f}|{item['p95_ms']:.1f}|"
            f"{item['unanswerable_return_rate']:.3f}"
            if item["unanswerable_return_rate"] is not None
            else f"|{item['model']}|{item['split']}|{item['answerable']}|"
            f"{item['recall'] or 0:.3f}|{item['ndcg'] or 0:.3f}|{item['mrr'] or 0:.3f}|"
            f"{item['p50_ms']:.1f}|{item['p95_ms']:.1f}|-"
        )
    lines.extend(
        [
            "",
            "## 资源与未完成项",
            "",
            "模型加载、文档向量化、查询延迟和模型维度见 `manifest.json`。",
            (
                "OpenAI 没有可用密钥时会保留为 unavailable，不会用 hash 向量冒充 "
                "`text-embedding-3-small`。"
            ),
            json.dumps(metadata["unavailable"], ensure_ascii=False),
            "",
            (
                "逐题结果见 `results.json`；如要把结论用于产品阈值，先人工复核 `labels.json`，"
                "再使用 `--labels` 重跑。"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def load_model(spec: ExperimentSpec, cache: str | None):
    if spec.model == OPENAI_MODEL:
        return OpenAIEmbedder(spec.model), None
    model = load_sentence_transformer(spec.model, cache)
    reranker = reranker_model(BGE_RERANKER, cache) if spec.strategy == "hybrid_rerank" else None
    return model, reranker


def run_spec(
    spec: ExperimentSpec,
    model,
    reranker,
    chunks: list[dict],
    questions: list[dict],
    sparse: SparseIndex,
    output: Path,
) -> tuple[list[dict], dict]:
    documents = [chunk["content"] for chunk in chunks]
    model_cache_key = hashlib.sha256(spec.model.encode()).hexdigest()[:12]
    vector_cache = output / f"{model_cache_key}-document-vectors.npy"
    document_vectors_cached = False
    if vector_cache.exists():
        document_vectors = np.load(vector_cache, allow_pickle=False)
        if document_vectors.shape[0] != len(documents):
            tick = time.perf_counter()
            document_vectors = encode_documents(model, documents)
            np.save(vector_cache, document_vectors)
        else:
            document_vectors_cached = True
            print(f"loaded document vectors {vector_cache.name}", flush=True)
    else:
        tick = time.perf_counter()
        document_vectors = encode_documents(model, documents)
        np.save(vector_cache, document_vectors)
    document_encode_ms = (
        round((time.perf_counter() - tick) * 1000, 2) if not document_vectors_cached else None
    )
    if document_vectors.ndim != 2 or not np.isfinite(document_vectors).all():
        raise RuntimeError(f"{spec.name} produced invalid document vectors")
    query_cache: dict[str, np.ndarray] = {}
    output_rows: list[dict] = []
    warmup = questions[0]["query"] if questions else "岗位技能"
    if isinstance(model, OpenAIEmbedder):
        query_cache[warmup] = model.encode([warmup])[0]
    else:
        query_cache[warmup] = encode_sentence_transformer(model, [warmup], query=True)[0]
    for question in questions:
        started = time.perf_counter()
        if question["query"] not in query_cache:
            if isinstance(model, OpenAIEmbedder):
                query_cache[question["query"]] = model.encode([question["query"]])[0]
            else:
                query_cache[question["query"]] = encode_sentence_transformer(
                    model, [question["query"]], query=True
                )[0]
        query_vector = query_cache[question["query"]]
        dense_scores = document_vectors @ query_vector
        sparse_scores = sparse.score(question["query"]) if spec.strategy != "dense" else None
        rerank_scores = None
        if spec.strategy == "hybrid_rerank":
            candidate_indices = reciprocal_rank_fusion(
                top_indices(dense_scores, DEFAULT_DENSE_TOP_K),
                top_indices(sparse_scores, DEFAULT_SPARSE_TOP_K),
            )[:DEFAULT_RERANK_POOL]
            values = encode_rerank(
                reranker,
                question["query"],
                [documents[index] for index in candidate_indices],
            )
            rerank_scores = np.full(len(chunks), -np.inf, dtype=np.float32)
            for index, value in zip(candidate_indices, values, strict=True):
                rerank_scores[index] = value
        job_ids = rank_job_ids(
            [chunk["job_id"] for chunk in chunks],
            dense_scores,
            sparse_scores,
            rerank_scores,
            dense_top_k=DEFAULT_DENSE_TOP_K,
            sparse_top_k=DEFAULT_SPARSE_TOP_K,
            rerank_pool=DEFAULT_RERANK_POOL,
            strategy=spec.strategy,
        )[:5]
        relevant = [label["job_id"] for label in question["relevance"] if label["grade"] > 0]
        output_rows.append(
            {
                "model": spec.name,
                "case_id": question["id"],
                "split": question["split"],
                "variant": question["variant"],
                "relevant_count": len(relevant),
                "job_ids": job_ids,
                "metrics": retrieval_metrics(job_ids, relevant),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "dense_top_score": round(float(dense_scores[top_indices(dense_scores, 1)[0]]), 6),
                "sparse_top_score": round(float(sparse_scores[top_indices(sparse_scores, 1)[0]]), 6)
                if sparse_scores is not None and len(sparse_scores)
                else None,
            }
        )
    save(output / f"{spec.name}-document-vectors.npy.json", {"shape": list(document_vectors.shape)})
    return output_rows, {
        "model": spec.model,
        "strategy": spec.strategy,
        "dimensions": int(document_vectors.shape[1]),
        "document_encode_ms": document_encode_ms,
        "document_vectors_cached": document_vectors_cached,
        "document_vector_cache": vector_cache.name,
        "query_count": len(questions),
    }


async def main(args) -> None:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot_path = Path(args.corpus).resolve()
    source_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    selected_jobs = source_snapshot["jobs"]
    if args.max_jobs and args.max_jobs < len(selected_jobs):
        selected_jobs = sorted(selected_jobs, key=lambda job: job["id"])[: args.max_jobs]
    snapshot = {
        **source_snapshot,
        "jobs": selected_jobs,
        "selection": (
            f"{source_snapshot.get('selection', 'frozen corpus')}; "
            f"deterministic first {len(selected_jobs)} jobs by id"
            if len(selected_jobs) != len(source_snapshot["jobs"])
            else source_snapshot.get("selection", "frozen corpus")
        ),
    }
    save(output / "corpus.json", snapshot)
    corpus_hash = hashlib.sha256((output / "corpus.json").read_bytes()).hexdigest()
    labels_path = Path(args.labels).resolve() if args.labels else None
    if args.max_jobs and args.max_jobs < len(source_snapshot["jobs"]) and labels_path:
        raise ValueError(
            "--max-jobs creates a new corpus; omit --labels to generate matching silver labels"
        )
    questions, label_status = build_questions(
        snapshot,
        labels_path,
        corpus_hash,
    )
    save(output / "labels.json", {"corpus_sha256": corpus_hash, "questions": questions})
    chunks = await load_chunks(snapshot)
    chunk_hash = hashlib.sha256(
        "\n".join(chunk["content_hash"] for chunk in chunks).encode()
    ).hexdigest()
    sparse = SparseIndex([chunk["content"] for chunk in chunks])
    cache = os.getenv("SEMANTIC_CACHE_DIR") or str(Path("../../outputs/model-cache").resolve())
    requested = {item.strip() for item in args.models.split(",") if item.strip()}
    specs = [spec for spec in SPECS if spec.name in requested or "all" in requested]
    if not specs:
        known = ", ".join(spec.name for spec in SPECS)
        raise ValueError(f"No known model selected. Choose from: {known}")
    results: list[dict] = []
    model_metadata: dict[str, dict] = {}
    unavailable: dict[str, str] = {}
    attempted_names = {spec.name for spec in specs}
    previous_results: list[dict] = []
    previous_metadata: dict = {}
    results_path = output / "results.json"
    manifest_path = output / "manifest.json"
    if results_path.exists():
        previous_results = json.loads(results_path.read_text(encoding="utf-8"))
    if manifest_path.exists():
        previous_metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        model_metadata.update(previous_metadata.get("model_metadata", {}))
        unavailable.update(previous_metadata.get("unavailable", {}))
    started = time.perf_counter()
    embedding_models: dict[str, object] = {}
    for spec in specs:
        model_started = time.perf_counter()
        try:
            if spec.model in embedding_models:
                model = embedding_models[spec.model]
                reranker = (
                    reranker_model(BGE_RERANKER, cache)
                    if spec.strategy == "hybrid_rerank"
                    else None
                )
            else:
                model, reranker = load_model(spec, cache)
                embedding_models[spec.model] = model
            rows, metadata = run_spec(spec, model, reranker, chunks, questions, sparse, output)
            metadata["load_and_run_ms"] = round((time.perf_counter() - model_started) * 1000, 2)
            model_metadata[spec.name] = metadata
            results.extend(rows)
            unavailable.pop(spec.name, None)
            if isinstance(model, OpenAIEmbedder):
                model.close()
            print(f"completed {spec.name}: {len(rows)} queries", flush=True)
        except Exception as exc:
            unavailable[spec.name] = f"{type(exc).__name__}: {exc}"
            print(f"unavailable {spec.name}: {unavailable[spec.name]}", flush=True)
    combined_results = [
        item for item in previous_results if item.get("model") not in attempted_names
    ] + results
    names = list(dict.fromkeys(item["model"] for item in combined_results))
    save(results_path, combined_results)
    summary = calculate_summary(combined_results, names)
    metadata = {
        "corpus_sha256": corpus_hash,
        "chunk_sha256": chunk_hash,
        "jobs": len(snapshot["jobs"]),
        "source_corpus_sha256": source_hash,
        "max_jobs": args.max_jobs,
        "chunks": len(chunks),
        "knowledge_version": JOB_KNOWLEDGE_VERSION,
        "cases": len(questions),
        "label_status": label_status,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: package_version(name)
            for name in ("sqlalchemy", "numpy", "torch", "sentence-transformers", "transformers")
        },
        "model_metadata": model_metadata,
        "parameters": {
            "metric_k_jobs": 5,
            "dense_top_k_chunks": DEFAULT_DENSE_TOP_K,
            "sparse_top_k_chunks": DEFAULT_SPARSE_TOP_K,
            "rerank_pool_chunks": DEFAULT_RERANK_POOL,
            "rrf_constant": DEFAULT_RRF_K,
            "sparse_tokenizer": "Chinese unigram+bigrams plus technical ASCII tokens",
            "normalize_embeddings": True,
            "device": os.getenv("EVAL_DEVICE", "cpu"),
            "batch_size": int(os.getenv("EVAL_BATCH_SIZE", "16")),
            "document_batch_size": int(os.getenv("EVAL_DOCUMENT_BATCHES", "64")),
            "max_seq_length": int(os.getenv("EVAL_MAX_SEQ_LENGTH", "512")),
            "latency_warmup_excluded": True,
            "production_index_unchanged": True,
        },
        "duration_seconds": round(time.perf_counter() - started, 3),
        "unavailable": unavailable,
        "summary": summary,
        "paid_llm_calls": 0,
    }
    save(output / "manifest.json", metadata)
    (output / "report.md").write_text(markdown_report(metadata), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True, help="Frozen corpus.json")
    parser.add_argument(
        "--labels",
        help="Reviewed labels.json; otherwise silver labels are generated",
    )
    parser.add_argument("--output", default="../../outputs/evaluation-embeddings-v1")
    parser.add_argument(
        "--max-jobs",
        type=int,
        help="Use a deterministic smaller pilot corpus; omit for the full frozen snapshot",
    )
    parser.add_argument(
        "--models",
        default="all",
        help="Comma-separated names from the report; default runs all requested candidates",
    )
    args = parser.parse_args()
    asyncio.run(main(args))
