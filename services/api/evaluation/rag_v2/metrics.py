from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from . import METRICS_VERSION


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _grades(row: Mapping[str, Any]) -> dict[str, int]:
    raw = row.get("relevant_grades") or row.get("grades") or {}
    if isinstance(raw, Mapping):
        return {str(key): int(value) for key, value in raw.items() if int(value) >= 0}
    return {
        str(item.get("job_id")): int(item.get("grade", 0)) for item in raw if item.get("job_id")
    }


def precision_at(ranking: Iterable[str], relevant: set[str], k: int) -> float:
    ids = _unique(ranking)[:k]
    return sum(item in relevant for item in ids) / k if k else 0.0


def recall_at(ranking: Iterable[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    ids = _unique(ranking)[:k]
    return sum(item in relevant for item in ids) / len(relevant)


def hit_at(ranking: Iterable[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    return float(any(item in relevant for item in _unique(ranking)[:k]))


def ndcg_at(ranking: Iterable[str], grades: Mapping[str, int], k: int) -> float | None:
    positive = [grade for grade in grades.values() if grade > 0]
    if not positive:
        return None
    ids = _unique(ranking)[:k]
    dcg = sum(
        (2 ** max(0, grades.get(item, 0)) - 1) / math.log2(index + 2)
        for index, item in enumerate(ids)
    )
    ideal = sorted(positive, reverse=True)[:k]
    ideal_dcg = sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(ideal))
    return dcg / ideal_dcg if ideal_dcg else None


def mrr_at(ranking: Iterable[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    return next(
        (1 / index for index, item in enumerate(_unique(ranking)[:k], start=1) if item in relevant),
        0.0,
    )


def average_precision(ranking: Iterable[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    hits = 0
    total = 0.0
    for index, item in enumerate(_unique(ranking), start=1):
        if item in relevant:
            hits += 1
            total += hits / index
    return total / len(relevant)


def bootstrap_ci(
    values: Iterable[float | None], *, seed: int = 20260910, iterations: int = 1000
) -> list[float | None]:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not clean:
        return [None, None]
    if len(clean) == 1:
        return [clean[0], clean[0]]
    rng = random.Random(seed)
    samples = []
    for _ in range(max(100, iterations)):
        samples.append(sum(clean[rng.randrange(len(clean))] for _ in clean) / len(clean))
    samples.sort()
    return [samples[int(0.025 * (len(samples) - 1))], samples[int(0.975 * (len(samples) - 1))]]


def _row_metrics(
    row: Mapping[str, Any],
    ranking: Iterable[str],
    *,
    k: int = 5,
    candidate_k: tuple[int, int] = (20, 50),
) -> dict[str, float | None]:
    grades = _grades(row)
    relevant = {job_id for job_id, grade in grades.items() if grade > 0}
    ranked = _unique(ranking)
    candidates = _unique(row.get("candidate_job_ids") or row.get("candidate_ids") or ranked)
    evidence_relevant = set(str(item) for item in row.get("evidence_relevant_ids", []))
    citations = set(str(item) for item in row.get("citation_job_ids", []))
    required_evidence = set(
        str(item) for item in row.get("required_evidence_ids", evidence_relevant)
    )
    result: dict[str, float | None] = {
        "precision@5": precision_at(ranked, relevant, 5),
        "recall@5": recall_at(ranked, relevant, 5),
        "recall@10": recall_at(ranked, relevant, 10),
        "ndcg@5": ndcg_at(ranked, grades, 5),
        "ndcg@10": ndcg_at(ranked, grades, 10),
        "mrr@10": mrr_at(ranked, relevant, 10),
        "hit@5": hit_at(ranked, relevant, 5),
        "map": average_precision(ranked, relevant),
        "evidence_recall@5": recall_at(ranked, evidence_relevant, 5),
        "evidence_precision@5": precision_at(ranked, evidence_relevant, 5)
        if evidence_relevant
        else None,
        "citation_coverage": len(citations & required_evidence) / len(required_evidence)
        if required_evidence
        else None,
    }
    for candidate_k_value in candidate_k:
        candidate_recall = recall_at(candidates, relevant, candidate_k_value)
        result[f"candidate_recall@{candidate_k_value}"] = candidate_recall
        result[f"candidate_hit@{candidate_k_value}"] = hit_at(
            candidates, relevant, candidate_k_value
        )
        result[f"recall_ceiling@{candidate_k_value}"] = (
            min(1.0, candidate_k_value / len(relevant)) if relevant else None
        )
        ceiling = result[f"recall_ceiling@{candidate_k_value}"]
        result[f"ceiling_normalized_recall@{candidate_k_value}"] = (
            candidate_recall / ceiling if ceiling else None
        )
    actual_answerability = str(row.get("answerability", "answerable"))
    predicted_no_answer = bool(row.get("predicted_no_answer", not ranked))
    result["no_answer_predicted"] = float(predicted_no_answer)
    result["no_answer_true"] = float(actual_answerability == "unanswerable")
    result["no_answer_tp"] = float(predicted_no_answer and actual_answerability == "unanswerable")
    result["no_answer_fp"] = float(predicted_no_answer and actual_answerability == "answerable")
    result["no_answer_fn"] = float(
        (not predicted_no_answer) and actual_answerability == "unanswerable"
    )
    return result


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return sum(values) / len(values) if values else None


def _no_answer_metrics(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    tp = sum(float(row.get("no_answer_tp", 0)) for row in rows)
    fp = sum(float(row.get("no_answer_fp", 0)) for row in rows)
    fn = sum(float(row.get("no_answer_fn", 0)) for row in rows)
    answerable = sum(not bool(row.get("no_answer_true")) for row in rows)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "no_answer_precision": precision,
        "no_answer_recall": recall,
        "no_answer_f1": f1,
        "false_positive_rate": fp / answerable if answerable else None,
    }


def _bootstrap_aggregate_metric(
    rows: list[dict[str, Any]], key: str, *, seed: int, iterations: int
) -> list[float | None]:
    if not rows:
        return [None, None]
    rng = random.Random(seed)
    samples: list[float | None] = []
    for _ in range(max(100, iterations)):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        samples.append(_no_answer_metrics(sample).get(key))
    return bootstrap_ci(samples, seed=seed + 1, iterations=iterations)


def aggregate_metrics(
    rows: Iterable[Mapping[str, Any]],
    ranking_key: str = "ranking",
    *,
    seed: int = 20260910,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    source_rows = [dict(row) for row in rows]
    evaluated = []
    for row in source_rows:
        ranking = row.get(ranking_key) or row.get("ranked_job_ids") or []
        evaluated.append({**row, **_row_metrics(row, ranking)})
    keys = (
        [
            key
            for key in evaluated[0]
            if key not in source_rows[0]
            and key
            not in {
                "no_answer_true",
                "no_answer_predicted",
                "no_answer_tp",
                "no_answer_fp",
                "no_answer_fn",
            }
        ]
        if evaluated
        else []
    )
    metrics: dict[str, dict[str, Any]] = {}
    for index, key in enumerate(keys):
        values = [row.get(key) for row in evaluated]
        metrics[key] = {
            "value": _mean_metric(evaluated, key),
            "ci95": bootstrap_ci(values, seed=seed + index, iterations=bootstrap_iterations),
        }
    no_answer = _no_answer_metrics(evaluated)
    for offset, (key, value) in enumerate(no_answer.items(), start=len(metrics)):
        metrics[key] = {
            "value": value,
            "ci95": _bootstrap_aggregate_metric(
                evaluated, key, seed=seed + offset, iterations=bootstrap_iterations
            ),
        }
    slices: dict[str, dict[str, Any]] = {}
    for field in ("query_type", "platform", "job_type", "role_direction"):
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in evaluated:
            buckets[str(row.get(field, "unknown"))].append(row)
        slices[field] = {}
        for bucket, bucket_rows in sorted(buckets.items()):
            slices[field][bucket] = {key: {"value": _mean_metric(bucket_rows, key)} for key in keys}
    flat = {key: value["value"] for key, value in metrics.items()}
    return {
        "metrics_version": METRICS_VERSION,
        "count": len(evaluated),
        "metrics": metrics,
        "flat_metrics": flat,
        "slices": slices,
        "per_query": evaluated,
        "bootstrap": {"seed": seed, "iterations": bootstrap_iterations, "confidence": 0.95},
    }
