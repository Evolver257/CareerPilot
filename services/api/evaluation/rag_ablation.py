"""Reproducible staged RAG ablation over recorded retrieval observations."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from evaluation.metrics import graded_retrieval_metrics
from evaluation.schemas import RAGEvaluationCase, assert_gold_ready


@dataclass(frozen=True)
class RAGAblationConfig:
    chunk_size: int = 256
    chunk_overlap: int = 32
    dense_top_k: int = 30
    sparse_top_k: int = 30
    final_top_k: int = 10
    rrf_k: int = 60
    dense_weight: float = 0.45
    sparse_weight: float = 0.55
    metadata_filter: bool = True
    query_rewrite: bool = True
    reranker_enabled: bool = True
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_top_k: int = 12
    minimum_relevance: float = 0.42

    def __post_init__(self) -> None:
        if self.chunk_size < 64 or self.chunk_size > 2048:
            raise ValueError("chunk_size must be between 64 and 2048")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")
        if min(self.dense_top_k, self.sparse_top_k, self.final_top_k, self.reranker_top_k) < 1:
            raise ValueError("retrieval Top-K values must be positive")
        if self.rrf_k < 1:
            raise ValueError("rrf_k must be positive")
        if not 0 <= self.dense_weight <= 1 or not 0 <= self.sparse_weight <= 1:
            raise ValueError("retrieval weights must be between 0 and 1")
        if abs(self.dense_weight + self.sparse_weight - 1) > 0.001:
            raise ValueError("dense_weight and sparse_weight must sum to 1")
        if not 0 <= self.minimum_relevance <= 1:
            raise ValueError("minimum_relevance must be between 0 and 1")

    def key(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def staged_configs(base: RAGAblationConfig | None = None) -> list[RAGAblationConfig]:
    """A bounded one-variable-at-a-time matrix; not an explosive Cartesian product."""

    base = base or RAGAblationConfig()
    configs = [base]
    stages: list[tuple[str, list[Any]]] = [
        ("chunk_size", [128, 256, 384, 512]),
        ("chunk_overlap", [0, 32, 64, 96]),
        ("rrf_k", [20, 60, 100]),
        ("final_top_k", [5, 8, 12, 20]),
        ("reranker_enabled", [False, True]),
        ("query_rewrite", [False, True]),
        ("metadata_filter", [False, True]),
        ("minimum_relevance", [0.30, 0.42, 0.55, 0.68]),
    ]
    for field, values in stages:
        for value in values:
            candidate = replace(base, **{field: value})
            if candidate not in configs:
                configs.append(candidate)
    for dense_weight in (0.0, 0.3, 0.5, 0.7, 1.0):
        candidate = replace(
            base,
            dense_weight=dense_weight,
            sparse_weight=round(1.0 - dense_weight, 10),
        )
        if candidate not in configs:
            configs.append(candidate)
    return configs


def evaluate_recorded(
    cases: list[RAGEvaluationCase],
    observations: list[dict[str, Any]],
    config: RAGAblationConfig,
    *,
    enforce_config_id: bool = False,
) -> dict[str, Any]:
    if enforce_config_id:
        observations = [
            item for item in observations if str(item.get("config_id")) == config.key()
        ]
        if not observations:
            raise ValueError(
                f"Missing retrieval observations for config {config.key()}; "
                "each ablation configuration must rerun retrieval against its own index snapshot"
            )
    by_case = {str(item["case_id"]): item for item in observations}
    rows = []
    for case in cases:
        observed = by_case.get(case.case_id, {})
        ids = [str(item) for item in observed.get("retrieved_document_ids", [])]
        grades = {item.document_id: item.grade for item in case.judgments}
        hard = [item.document_id for item in case.judgments if item.hard_negative]
        metrics = graded_retrieval_metrics(ids, grades, hard, k=config.final_top_k)
        predicted_no_answer = bool(observed.get("predicted_no_answer", not ids))
        metrics["no_answer_accuracy"] = float(predicted_no_answer == (not case.answerable))
        metrics["latency_ms"] = float(observed.get("latency_ms", 0))
        metrics["context_tokens"] = int(observed.get("context_tokens", 0))
        rows.append({"case_id": case.case_id, "topic": case.topic, **metrics})

    return summarize_recorded_rows(rows, config)


def summarize_recorded_rows(
    rows: list[dict[str, Any]], config: RAGAblationConfig
) -> dict[str, Any]:
    numeric = {
        key: [float(row[key]) for row in rows if isinstance(row.get(key), int | float)]
        for key in {
            "precision",
            "recall",
            "mrr",
            "ndcg",
            "context_precision",
            "context_recall",
            "hard_negative_rejection_rate",
            "false_evidence_rate",
            "no_answer_accuracy",
            "latency_ms",
            "context_tokens",
        }
    }
    summary = {key: mean(values) if values else None for key, values in numeric.items()}
    return {"config_id": config.key(), "config": asdict(config), "summary": summary, "cases": rows}


def pareto_frontier(results: list[dict[str, Any]]) -> list[str]:
    points = []
    for result in results:
        summary = result["summary"]
        quality = mean(
            value
            for value in [
                summary.get("recall"),
                summary.get("ndcg"),
                summary.get("no_answer_accuracy"),
            ]
            if value is not None
        )
        points.append(
            (
                result["config_id"],
                quality,
                summary.get("latency_ms") or 0,
                summary.get("context_tokens") or 0,
            )
        )
    return [
        candidate[0]
        for candidate in points
        if not any(
            other[1] >= candidate[1]
            and other[2] <= candidate[2]
            and other[3] <= candidate[3]
            and other != candidate
            for other in points
        )
    ]


def _load_jsonl(path: Path, schema=None):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            rows.append(schema.model_validate(value) if schema else value)
    return rows


def run(dataset: Path, observations: Path, output_root: Path, require_gold: bool) -> Path:
    cases = _load_jsonl(dataset, RAGEvaluationCase)
    if require_gold:
        assert_gold_ready(cases)
    observed = _load_jsonl(observations)
    results = [
        evaluate_recorded(cases, observed, config, enforce_config_id=True)
        for config in staged_configs()
    ]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    output = output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    payload = {
        "run_id": run_id,
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "label_status": sorted({item.annotation_status for item in cases}),
        "pareto_frontier": pareto_frontier(results),
        "experiments": results,
    }
    (output / "rag_ablation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--output", default="../../outputs/rag-ablation")
    parser.add_argument("--require-gold", action="store_true")
    args = parser.parse_args()
    print(run(Path(args.dataset), Path(args.observations), Path(args.output), args.require_gold))
