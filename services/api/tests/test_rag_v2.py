from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.annotation import requires_adjudication, weighted_cohen_kappa
from evaluation.rag_v2.annotations import AnnotationStore
from evaluation.rag_v2.candidates import generate_candidate_pool
from evaluation.rag_v2.dataset import (
    build_corpus_job,
    build_snapshot,
    deduplicate_jobs,
)
from evaluation.rag_v2.metrics import aggregate_metrics
from evaluation.rag_v2.queries import build_query_seed
from evaluation.rag_v2.splits import assign_splits, validate_frozen_splits


def job(job_id: str, title: str, description: str, *, platform: str = "boss") -> dict:
    return {
        "id": job_id,
        "platform": platform,
        "external_job_id": job_id,
        "title": title,
        "description": description,
        "location": "武汉",
        "job_type": "Full-time",
        "source_url": f"https://example.test/{job_id}",
        "raw_data": {"company_name": "测试公司"},
    }


def test_react_and_react_are_not_collapsed_into_frontend() -> None:
    react = build_corpus_job(
        job("1", "React 前端工程师", "负责 React 页面开发和 TypeScript 组件维护" * 5)
    )
    react_agent = build_corpus_job(
        job("2", "ReAct Agent 工程师", "负责 ReAct 推理流程和工具调用编排" * 5)
    )
    assert react is not None and react_agent is not None
    assert react.role_direction == "前端"
    assert react_agent.role_direction == "AI Agent"


def test_dedup_uses_exact_and_near_duplicate_keys() -> None:
    first = job("1", "RAG 工程师", "负责向量检索和知识库问答" * 20)
    same_url = {
        **job("2", "另一个标题", "完全不同但来源重复" * 20),
        "source_url": first["source_url"],
    }
    near = {
        **first,
        "id": "3",
        "external_job_id": "3",
        "platform": "zhaopin",
        "source_url": "https://example.test/3",
    }
    items, stats = deduplicate_jobs([first, same_url, near])
    assert len(items) == 1
    assert stats["duplicate_count"] == 2


def test_snapshot_is_reproducible_except_generation_timestamp() -> None:
    jobs = [
        job(
            str(index),
            f"后端工程师 {index}",
            "负责 Python FastAPI 服务开发" * 12,
            platform="boss" if index % 2 else "zhaopin",
        )
        for index in range(20)
    ]
    first, manifest_a = build_snapshot(jobs, sample_size=8, seed=7)
    second, manifest_b = build_snapshot(jobs, sample_size=8, seed=7)
    assert [item.job_id for item in first] == [item.job_id for item in second]
    assert manifest_a["corpus_sha256"] == manifest_b["corpus_sha256"]


def test_seed_has_requested_distribution() -> None:
    rows = build_query_seed()
    counts = {
        value: sum(row["query_type"] == value for row in rows)
        for value in {row["query_type"] for row in rows}
    }
    assert len(rows) == 200
    assert counts == {
        "literal": 50,
        "paraphrase": 50,
        "multi_constraint": 30,
        "skill_requirements": 20,
        "learning_path": 20,
        "comparison": 10,
        "no_answer": 10,
        "hard_negative": 10,
    }
    assert all(row["requires_human_review"] and row["generator_model"] is None for row in rows)


def test_split_keeps_template_groups_together() -> None:
    stamped, manifest = assign_splits(build_query_seed(), seed=11)
    validate_frozen_splits(stamped, manifest)
    assert manifest["test_frozen"]
    assert sum(manifest["counts"].values()) == 200
    assert manifest["counts"]["train"] >= manifest["counts"]["dev"]


def test_candidate_pool_is_fixed_size_and_has_channel_provenance() -> None:
    queries = build_query_seed()[:2]
    corpus = [
        build_corpus_job(
            job(str(index), "RAG 工程师", "负责 RAG 知识库和 Python 服务" * 12)
        ).model_dump(mode="json")
        for index in range(40)
    ]
    rows = generate_candidate_pool(queries, corpus, pool_size=20, seed=3)
    assert len(rows) == 40
    assert all(
        20 <= sum(row["query_id"] == query["query_id"] for row in rows) <= 40 for query in queries
    )
    assert set().union(*(set(row["channels"]) for row in rows)) >= {
        "postgres_bm25",
        "qwen3_embedding_0.6b",
        "hybrid",
        "job_skill_fact",
        "random",
    }


def test_metrics_include_ceiling_and_bootstrap_ci() -> None:
    result = aggregate_metrics(
        [
            {
                "query_id": "q1",
                "answerability": "answerable",
                "relevant_grades": {"a": 3, "b": 2, "c": 1},
                "candidate_job_ids": ["a", "x"],
                "ranking": ["a", "x"],
            },
            {
                "query_id": "q2",
                "answerability": "unanswerable",
                "relevant_grades": {},
                "candidate_job_ids": ["x"],
                "ranking": ["x"],
                "predicted_no_answer": True,
            },
        ],
        bootstrap_iterations=100,
    )
    assert result["metrics"]["candidate_recall@20"]["value"] == pytest.approx(1 / 3)
    assert result["metrics"]["candidate_recall@20"]["ci95"]
    assert result["flat_metrics"]["recall_ceiling@20"] == 1.0
    assert "no_answer_f1" in result["metrics"]


def test_annotation_conflict_and_kappa_gate(tmp_path: Path) -> None:
    store = AnnotationStore(tmp_path / "annotations.jsonl", tmp_path / "adjudications.jsonl")
    base = {
        "dataset_version": "rag-v2.0.0",
        "query_id": "q1",
        "job_id": "j1",
        "relevance_grade": 0,
        "hard_constraint_violation": "no",
        "answerability_judgment": "answerable",
        "matched_requirements": [],
        "missing_requirements": [],
        "evidence_spans": [],
        "confidence": "high",
        "annotation_note": "",
        "status": "submitted",
    }
    store.upsert({**base, "annotator_id": "a"})
    store.upsert({**base, "annotator_id": "b", "relevance_grade": 3})
    assert len(store.conflicts()) == 1
    assert requires_adjudication(0, 3)
    assert weighted_cohen_kappa([0, 1, 2, 3], [0, 1, 2, 2]) > 0.7
