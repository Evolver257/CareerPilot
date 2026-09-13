"""Metrics for memory extraction, retrieval, personalization, and privacy."""

from __future__ import annotations

import statistics
from typing import Any

from evaluation.schemas import MemoryEvaluationCase, MemoryTaskObservation


def _candidate_key(item: Any) -> tuple[str, str | None]:
    return str(item.memory_type), item.memory_key


def _match_candidates(expected: list[Any], observed: list[Any]) -> list[tuple[Any, Any]]:
    """Match each expected item once; a missing gold key acts as a type wildcard."""

    matched_observed: set[int] = set()
    pairs: list[tuple[Any, Any]] = []
    for expected_item in expected:
        candidate = next(
            (
                index
                for index, observed_item in enumerate(observed)
                if index not in matched_observed
                and _candidate_key(expected_item)[0] == _candidate_key(observed_item)[0]
                and (
                    expected_item.memory_key is None
                    or expected_item.memory_key == observed_item.memory_key
                )
            ),
            None,
        )
        if candidate is not None:
            matched_observed.add(candidate)
            pairs.append((expected_item, observed[candidate]))
    return pairs


def evaluate_memory_case(
    case: MemoryEvaluationCase,
    observation: MemoryTaskObservation,
) -> dict[str, Any]:
    if case.case_id != observation.case_id:
        raise ValueError("Case and observation IDs do not match")

    expected = [item for item in case.expected_candidates if item.required]
    observed = observation.extracted_candidates
    matched_pairs = _match_candidates(expected, observed)
    matched_count = len(matched_pairs)
    key_pairs = [pair for pair in matched_pairs if pair[0].memory_key is not None]
    quote_checks = [
        bool(item.source_quote) and item.source_quote in case.user_query
        for item in observed
    ]
    unsupported = sum(
        not item.supported or not quote_ok
        for item, quote_ok in zip(observed, quote_checks, strict=True)
    )

    retrieved = list(dict.fromkeys(observation.retrieved_memory_ids))
    top_k = retrieved[: case.retrieval_top_k]
    expected_retrieval = set(case.expected_retrieval_memory_ids)
    retrieval_hits = sum(item in expected_retrieval for item in top_k)
    first_rank = next(
        (index + 1 for index, item in enumerate(top_k) if item in expected_retrieval),
        None,
    )
    no_expected_retrieval = not expected_retrieval
    sensitive_violation = (
        case.expected_sensitive_rejection and observation.sensitive_memory_saved
    )
    stale_rate = (
        len(set(observation.stale_memory_ids) & set(top_k)) / len(top_k)
        if top_k
        else 0.0
    )
    wrong_user_rate = (
        len(set(observation.wrong_user_memory_ids) & set(top_k)) / len(top_k)
        if top_k
        else 0.0
    )
    irrelevant_rate = (
        len(set(observation.irrelevant_memory_ids) & set(top_k)) / len(top_k)
        if top_k
        else 0.0
    )

    return {
        "case_id": case.case_id,
        "category": case.category,
        "candidate_precision": (
            matched_count / len(observed) if observed else (1.0 if not expected else 0.0)
        ),
        "candidate_recall": matched_count / len(expected) if expected else 1.0,
        "memory_type_accuracy": (
            sum(
                expected_item.memory_type == observed_item.memory_type
                for expected_item, observed_item in matched_pairs
            )
            / len(observed)
            if observed
            else 1.0
        ),
        "memory_key_accuracy": (
            sum(
                expected_item.memory_key == observed_item.memory_key
                for expected_item, observed_item in key_pairs
            )
            / len(key_pairs)
            if key_pairs
            else 1.0
        ),
        "source_quote_accuracy": (
            sum(quote_checks) / len(quote_checks) if quote_checks else 1.0
        ),
        "unsupported_memory_rate": unsupported / len(observed) if observed else 0.0,
        "memory_recall_at_k": (
            retrieval_hits / len(expected_retrieval) if expected_retrieval else 1.0
        ),
        "memory_precision_at_k": (
            retrieval_hits / len(top_k) if top_k else (1.0 if no_expected_retrieval else 0.0)
        ),
        "memory_mrr": (
            1 / first_rank if first_rank else (1.0 if no_expected_retrieval else 0.0)
        ),
        "stale_memory_retrieval_rate": stale_rate,
        "wrong_user_leakage_rate": wrong_user_rate,
        "irrelevant_memory_injection_rate": irrelevant_rate,
        "sensitive_memory_save_violation": float(sensitive_violation),
        "task_completed": observation.task_completed,
        "token_usage": observation.token_usage,
        "error": observation.error,
    }


def aggregate_memory_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ValueError("No memory evaluation results")
    numeric_keys = [
        "candidate_precision",
        "candidate_recall",
        "memory_type_accuracy",
        "memory_key_accuracy",
        "source_quote_accuracy",
        "unsupported_memory_rate",
        "memory_recall_at_k",
        "memory_precision_at_k",
        "memory_mrr",
        "stale_memory_retrieval_rate",
        "wrong_user_leakage_rate",
        "irrelevant_memory_injection_rate",
        "sensitive_memory_save_violation",
    ]
    return {
        "cases": len(rows),
        **{key: statistics.fmean(float(row[key]) for row in rows) for key in numeric_keys},
        "task_completion_rate": statistics.fmean(bool(row["task_completed"]) for row in rows),
        "average_tokens_per_task": statistics.fmean(row["token_usage"] for row in rows),
        "error_rate": statistics.fmean(bool(row["error"]) for row in rows),
    }
