"""Run from services/api: python -m evaluation.run --semantic --rerank.

Uses the production chunker/indexer/retriever in an isolated SQLite database.
SQLite's lexical fallback is NOT PostgreSQL FTS/BM25; report this boundary.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import re
import statistics
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings
from app.llm.local_semantic import MODEL_REVISIONS, LocalSemanticProvider
from app.llm.provider import MockLLMProvider
from app.models.base import Base
from app.models.entities import Job, JobKnowledgeChunk, JobKnowledgeDocument
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.schemas.knowledge_search import JobKnowledgeSearchRequest
from app.services.agentic_rag import AgenticRAGPipeline
from app.services.job_knowledge import JOB_KNOWLEDGE_VERSION
from app.services.job_knowledge_rag import JobKnowledgeRAG
from app.services.knowledge_indexing import KnowledgeIndexService
from evaluation.cases import cases
from evaluation.metrics import retrieval_metrics, validate_labels


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def main(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot_path = Path(args.corpus).resolve() if args.corpus else output / "corpus.json"
    if not snapshot_path.exists():
        async with httpx.AsyncClient(base_url=args.api, timeout=30, trust_env=False) as client:
            jobs = []
            for page in range(1, 101):
                response = await client.get("/api/jobs", params={"page": page, "page_size": 100})
                response.raise_for_status()
                data = response.json()
                jobs.extend(data["items"])
                if len(jobs) >= data["total"] or not data["items"]:
                    break
        # Freeze a deterministic, deduplicated sample independent of retrieval results.
        unique = {}
        for job in jobs:
            content = re.sub(r"\s+", " ", job["description"]).strip()
            if len(content) >= 120:
                unique.setdefault(hashlib.sha256(content.encode()).hexdigest(), job)
        selected = [unique[key] for key in sorted(unique)[: args.jobs]]
        fields = [
            "id",
            "platform",
            "external_job_id",
            "title",
            "description",
            "location",
            "salary_min",
            "salary_max",
            "job_type",
            "education_requirement",
            "experience_requirement",
            "source_url",
            "content_hash",
        ]
        snapshot = {
            "captured_at": datetime.now(UTC).isoformat(),
            "source_total": len(jobs),
            "selection": "content-hash sorted, deduplicated, JD >=120 chars",
            "jobs": [{key: job.get(key) for key in fields} for job in selected],
        }
        save(snapshot_path, snapshot)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if args.corpus:
        save(output / "corpus.json", snapshot)
    corpus_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    questions = cases()
    labels_are_external = False
    for question in questions:
        labels = []
        for job in snapshot["jobs"]:
            content = job["title"] + "\n" + job["description"]
            match = re.search(question["criterion"], content, re.I)
            if match:
                labels.append(
                    {
                        "job_id": job["id"],
                        "grade": 1,
                        "evidence": content[max(0, match.start() - 70) : match.end() + 100],
                    }
                )
        question["relevance"] = labels
    if args.labels:
        reviewed = json.loads(Path(args.labels).read_text(encoding="utf-8"))
        if reviewed["corpus_sha256"] != corpus_hash:
            raise ValueError("Reviewed labels belong to a different corpus snapshot")
        questions = reviewed["questions"]
        labels_are_external = not all(
            str(question.get("label_status", "")).startswith("silver")
            for question in questions
        )
    validate_labels(questions, {job["id"] for job in snapshot["jobs"]})
    save(output / "labels.json", {"corpus_sha256": corpus_hash, "questions": questions})
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    results = []
    unavailable = {}
    started = time.perf_counter()
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
        docs = list((await session.scalars(select(JobKnowledgeDocument))).all())
        print(f"indexed {len(snapshot['jobs'])} jobs / {len(chunks)} chunks", flush=True)
        modes = (
            []
            if args.only_agentic
            else [
                ("lexical", "full_text", "none", mock),
                ("hash_hybrid", "hybrid", "local", mock),
            ]
        )
        real = None
        if args.semantic:
            real = LocalSemanticProvider(cache=os.getenv("SEMANTIC_CACHE_DIR"))
            try:
                embed_path = (
                    Path(args.embedding_cache).resolve()
                    if args.embedding_cache
                    else output / "embeddings.json"
                )
                embed_key = hashlib.sha256(
                    (
                        corpus_hash
                        + real.embedding_signature
                        + "\n".join(c.content_hash for c in chunks)
                    ).encode()
                ).hexdigest()
                cache = json.loads(embed_path.read_text()) if embed_path.exists() else {}
                if cache.get("key") == embed_key:
                    vectors = cache["vectors"]
                else:
                    vectors = await asyncio.to_thread(
                        real.encode,
                        [
                            "\n".join(
                                part
                                for part in (
                                    str(
                                        (chunk.chunk_metadata or {}).get("embedding_context")
                                        or ""
                                    ).strip(),
                                    chunk.content,
                                )
                                if part
                            )
                            for chunk in chunks
                        ],
                    )
                    save(embed_path, {"key": embed_key, "vectors": vectors})
                if not args.only_agentic:
                    modes += [
                        ("semantic_vector", "vector", "none", real),
                        ("semantic_hybrid", "hybrid", "local", real),
                    ]
                    if args.rerank:
                        modes.append(
                            ("semantic_hybrid_rerank", "hybrid", "cross_encoder", real)
                        )
                else:
                    # The normal mode loop installs cached vectors immediately
                    # before each semantic benchmark.  An agentic-only run skips
                    # that loop, so install the same vectors here instead of
                    # accidentally measuring a lexical-only fallback.
                    for chunk, vector in zip(chunks, vectors, strict=True):
                        chunk.embedding = vector
                        chunk.embedding_signature = real.embedding_signature
                        chunk.embedding_model = real.embedding_model
                        chunk.embedding_provider = real.embedding_provider_name
                    for doc in docs:
                        doc.current_embedding_signature = real.embedding_signature
                    await session.commit()
            except Exception as exc:
                unavailable["semantic"] = f"{type(exc).__name__}: {exc}"
        for name, retrieval_mode, rerank_mode, provider in modes:
            if provider is not mock:
                for chunk, vector in zip(chunks, vectors, strict=True):
                    chunk.embedding = vector
                    chunk.embedding_signature = provider.embedding_signature
                    chunk.embedding_model = provider.embedding_model
                    chunk.embedding_provider = provider.embedding_provider_name
                for doc in docs:
                    doc.current_embedding_signature = provider.embedding_signature
                await session.commit()
            # Warm-up excluded from request timings; model download is not inference latency.
            try:
                await JobKnowledgeRAG(session, provider).search(
                    JobKnowledgeSearchRequest(
                        query="岗位技能",
                        retrieval_mode=retrieval_mode,
                        rerank_mode=rerank_mode,
                        force_refresh=True,
                    )
                )
            except Exception as exc:
                unavailable[name] = f"{type(exc).__name__}: {exc}"
                continue
            for question in questions:
                tick = time.perf_counter()
                result = await JobKnowledgeRAG(session, provider).search(
                    JobKnowledgeSearchRequest(
                        query=question["query"],
                        retrieval_mode=retrieval_mode,
                        rerank_mode=rerank_mode,
                        top_k=20,
                        full_text_top_k=100,
                        vector_top_k=100,
                        force_refresh=True,
                    )
                )
                ids = list(dict.fromkeys(str(c.job_id) for c in result.citations))[:5]
                relevant = [
                    label["job_id"] for label in question["relevance"] if label["grade"] > 0
                ]
                metrics = retrieval_metrics(ids, relevant)
                results.append(
                    {
                        "mode": name,
                        "case_id": question["id"],
                        "split": question["split"],
                        "variant": question["variant"],
                        "relevant_count": len(relevant),
                        "job_ids": ids,
                        "metrics": metrics,
                        "latency_ms": round((time.perf_counter() - tick) * 1000, 2),
                        "warnings": result.warnings,
                    }
                )
            print(f"completed {name}", flush=True)
            save(output / "results.json", results)
        if args.agentic and real is not None and "semantic" not in unavailable:
            mode_name = "agentic_hybrid"
            modes.append((mode_name, "hybrid", "local", real))
            settings = Settings(
                rag_reranker="local",
                rag_llm_planner_enabled=False,
                rag_reflection_enabled=False,
                rag_workflow_timeout_seconds=180,
                semantic_cache_dir=os.getenv("SEMANTIC_CACHE_DIR"),
            )
            pipeline = AgenticRAGPipeline(
                JobKnowledgeRAG(session, real, settings),
                settings=settings,
            )
            for question in questions:
                tick = time.perf_counter()
                result = await pipeline.run(
                    JobKnowledgeSearchRequest(
                        query=question["query"],
                        top_k=20,
                        full_text_top_k=100,
                        vector_top_k=100,
                        force_refresh=True,
                    )
                )
                ids = list(
                    dict.fromkeys(
                        str(source.job_id)
                        for evidence in result.evidence
                        for source in evidence.sources
                    )
                )[:5]
                relevant = [
                    label["job_id"] for label in question["relevance"] if label["grade"] > 0
                ]
                results.append(
                    {
                        "mode": mode_name,
                        "case_id": question["id"],
                        "split": question["split"],
                        "variant": question["variant"],
                        "relevant_count": len(relevant),
                        "job_ids": ids,
                        "metrics": retrieval_metrics(ids, relevant),
                        "latency_ms": round((time.perf_counter() - tick) * 1000, 2),
                        "warnings": result.warnings,
                        "query_count": result.trace.query_count,
                        "evidence_count": len(result.evidence),
                    }
                )
            print(f"completed {mode_name}", flush=True)
            save(output / "results.json", results)
    await engine.dispose()
    summaries = []
    for name, *_ in modes:
        for split in ["dev", "test"]:
            group = [r for r in results if r["mode"] == name and r["split"] == split]
            labeled = [r for r in group if r["relevant_count"]]
            empty = [r for r in group if not r["relevant_count"]]
            if not group:
                continue
            summaries.append(
                {
                    "mode": name,
                    "split": split,
                    "answerable": len(labeled),
                    "unanswerable": len(empty),
                    **{
                        m: statistics.mean(r["metrics"][m] for r in labeled) if labeled else None
                        for m in ["recall", "ndcg", "mrr"]
                    },
                    "p50_ms": statistics.median(r["latency_ms"] for r in group),
                    "p95_ms": sorted(r["latency_ms"] for r in group)[
                        max(0, int(len(group) * 0.95) - 1)
                    ],
                    "empty_query_return_rate": sum(r["metrics"]["returned_any"] for r in empty)
                    / len(empty)
                    if empty
                    else None,
                }
            )
    metadata = {
        "corpus_sha256": corpus_hash,
        "jobs": len(snapshot["jobs"]),
        "chunks": len(chunks),
        "knowledge_version": JOB_KNOWLEDGE_VERSION,
        "cases": len(questions),
        "label_status": "external_labels_supplied"
        if labels_are_external
        else "silver_requires_human_review",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: version(name)
            for name in ["sqlalchemy", "numpy", "torch", "sentence-transformers", "transformers"]
        }
        if args.semantic and not unavailable.get("semantic")
        else {},
        "model_revisions": MODEL_REVISIONS if args.semantic else {},
        "parameters": {
            "metric_k_jobs": 5,
            "top_k_chunks": 20,
            "full_text_top_k": 100,
            "vector_top_k": 100,
            "rerank_pool": 40,
            "device": "cpu",
            "normalize_embeddings": True,
            "embedding_dimensions": 1024,
            "cache_bypassed": True,
            "omp_threads": os.getenv("OMP_NUM_THREADS"),
            "latency_warmup_excluded": True,
            "database": "sqlite-memory",
        },
        "duration_seconds": time.perf_counter() - started,
        "unavailable": unavailable,
        "summary": summaries,
        "generation_evaluated": False,
        "paid_llm_calls": 0,
    }
    save(output / "manifest.json", metadata)
    lines = [
        "# CareerPilot 检索对照实验报告",
        "",
        f"数据快照：{corpus_hash}",
        f"{len(snapshot['jobs'])} 个真实岗位，{len(chunks)} 个知识块，{len(questions)} 个问题。",
        "",
        "## 方法与边界",
        "",
        "使用生产切块、索引、混合检索与可选重排实现；"
        "隔离 SQLite 的词汇回退不是 PostgreSQL 全文检索，也不是 BM25。"
        "候选相关性按预先声明的规则生成，附原文证据，未经独立人工复核，属于 silver 评测。"
        "话题级拆分开发/测试，未按测试结果调参。不能将本报告数字宣传为人工金标准确率。",
        "",
        "Recall@5 分母为该问题全部标注相关岗位数；nDCG@5/MRR@5 基于去重岗位，不是知识块。"
        "无相关岗位问题不计入上述均值，单列仍返回候选的比例；返回候选不等于 Agent 作出错误回答。"
        "延迟是本地 CPU 预热后的检索耗时，不含生成、下载或线上网络。",
        "",
        "|方案|集合|有答案样本|Recall@5|nDCG@5|MRR@5|P50 ms|P95 ms|",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            f"|{s['mode']}|{s['split']}|{s['answerable']}|{s['recall'] or 0:.3f}|"
            f"{s['ndcg'] or 0:.3f}|{s['mrr'] or 0:.3f}|{s['p50_ms']:.1f}|{s['p95_ms']:.1f}|"
        )
    lines += [
        "",
        "## 未完成实验",
        "",
        json.dumps(unavailable, ensure_ascii=False),
        "",
        "本次未调用付费生成模型，不提供回答正确率、幻觉率或 Token 降幅结论。"
        "请先复核 labels.json，再使用 --labels 固定标注复跑。"
        "结果不佳同样保留，不预设语义重排一定提升。"
        "逐题结果见 results.json，参数及环境见 manifest.json。",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8010")
    parser.add_argument("--output", default="../../outputs/evaluation-v1")
    parser.add_argument("--jobs", type=int, default=120)
    parser.add_argument("--corpus", help="Reuse an existing frozen corpus.json snapshot")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--agentic", action="store_true")
    parser.add_argument("--only-agentic", action="store_true")
    parser.add_argument("--embedding-cache", help="Reuse a compatible embeddings.json file")
    parser.add_argument("--labels")
    args = parser.parse_args()
    if args.rerank and not args.semantic:
        parser.error("--rerank requires --semantic for the semantic comparison")
    if args.agentic and not args.semantic:
        parser.error("--agentic requires --semantic")
    if args.only_agentic and not args.agentic:
        parser.error("--only-agentic requires --agentic")
    asyncio.run(main(args))
