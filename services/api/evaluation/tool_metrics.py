"""Task-level and aggregate metrics for Agent tool-calling evaluation."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from typing import Any

from evaluation.schemas import (
    ExpectedToolCall,
    ObservedToolCall,
    ToolEvaluationCase,
    ToolTaskObservation,
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _arguments_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Gold arguments are a required subset; harmless provider defaults are allowed."""

    return all(
        key in actual and _canonical(actual[key]) == _canonical(value)
        for key, value in expected.items()
    )


def _pair_calls(
    expected: list[ExpectedToolCall], actual: list[ObservedToolCall]
) -> tuple[list[tuple[ExpectedToolCall, ObservedToolCall]], list[int], list[int]]:
    pairs: list[tuple[ExpectedToolCall, ObservedToolCall]] = []
    used_actual: set[int] = set()
    missing_expected: list[int] = []
    for expected_index, target in enumerate(expected):
        candidate = next(
            (
                index
                for index, observed in enumerate(actual)
                if index not in used_actual
                and observed.tool_name == target.tool_name
                and _arguments_match(target.arguments, observed.arguments)
            ),
            None,
        )
        if candidate is None:
            candidate = next(
                (
                    index
                    for index, observed in enumerate(actual)
                    if index not in used_actual and observed.tool_name == target.tool_name
                ),
                None,
            )
        if candidate is None:
            missing_expected.append(expected_index)
            continue
        used_actual.add(candidate)
        pairs.append((target, actual[candidate]))
    extra_actual = [index for index in range(len(actual)) if index not in used_actual]
    return pairs, missing_expected, extra_actual


def evaluate_tool_task(
    case: ToolEvaluationCase,
    observation: ToolTaskObservation,
) -> dict[str, Any]:
    if case.case_id != observation.case_id:
        raise ValueError("Case and observation IDs do not match")

    expected = [item for item in case.expected_calls if item.required and not item.forbidden]
    forbidden_names = {item.tool_name for item in case.expected_calls if item.forbidden}
    pairs, missing, extra = _pair_calls(expected, observation.calls)
    expected_names = [item.tool_name for item in expected]
    actual_names = [item.tool_name for item in observation.calls]
    matched_name_count = sum((Counter(expected_names) & Counter(actual_names)).values())
    precision = (
        matched_name_count / len(actual_names) if actual_names else (1.0 if not expected else 0.0)
    )
    recall = matched_name_count / len(expected_names) if expected_names else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    argument_fields = 0
    correct_fields = 0
    exact_arguments = 0
    for target, observed in pairs:
        argument_fields += len(target.arguments)
        correct_fields += sum(
            key in observed.arguments and _canonical(observed.arguments[key]) == _canonical(value)
            for key, value in target.arguments.items()
        )
        exact_arguments += int(_arguments_match(target.arguments, observed.arguments))

    statuses = Counter(item.status for item in observation.calls)
    duplicate_count = sum(item.duplicate for item in observation.calls)
    signatures: set[tuple[str, str]] = set()
    for item in observation.calls:
        signature = (item.tool_name, _canonical(item.arguments))
        if signature in signatures and not item.retry_of:
            duplicate_count += 1
        signatures.add(signature)
    unnecessary_count = sum(item.unnecessary for item in observation.calls) + len(extra)
    forbidden_count = sum(item.tool_name in forbidden_names for item in observation.calls)
    total_tokens = sum(item.prompt_tokens + item.completion_tokens for item in observation.calls)
    total_cost = sum(item.cost for item in observation.calls)
    denominator = len(observation.calls) or 1

    return {
        "case_id": case.case_id,
        "category": case.category,
        "tool_selection_precision": precision,
        "tool_selection_recall": recall,
        "tool_selection_f1": f1,
        "required_tool_recall": (len(expected) - len(missing)) / len(expected) if expected else 1.0,
        "exact_sequence_success": actual_names == expected_names,
        "forbidden_tool_violation": forbidden_count > 0,
        "argument_field_accuracy": correct_fields / argument_fields if argument_fields else 1.0,
        "argument_exact_call_accuracy": exact_arguments / len(pairs)
        if pairs
        else (1.0 if not expected else 0.0),
        "schema_valid_rate": (
            sum(item.schema_valid is not False for item in observation.calls) / denominator
        ),
        "semantic_argument_valid_rate": (
            sum(item.semantically_valid is not False for item in observation.calls) / denominator
        ),
        "invalid_call_rate": (
            sum(
                item.schema_valid is False or item.semantically_valid is False
                for item in observation.calls
            )
            / denominator
        ),
        "duplicate_call_rate": duplicate_count / denominator,
        "unnecessary_call_rate": unnecessary_count / denominator,
        "missing_required_call_rate": len(missing) / len(expected) if expected else 0.0,
        "execution_success_rate": statuses["SUCCESS"] / denominator,
        "retry_rate": sum(
            bool(item.retry_of) or item.status == "RETRYING" for item in observation.calls
        )
        / denominator,
        "task_completed": observation.task_completed,
        "tool_calls": len(observation.calls),
        "latency_ms": observation.total_latency_ms,
        "tokens": total_tokens,
        "cost": total_cost,
        "cost_per_success": total_cost if observation.task_completed else None,
        "tokens_per_success": total_tokens if observation.task_completed else None,
        "missing_expected_indexes": missing,
        "extra_actual_indexes": extra,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1))
    return ordered[index]


def aggregate_tool_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        raise ValueError("No tool evaluation results")
    rate_fields = [
        "tool_selection_precision",
        "tool_selection_recall",
        "tool_selection_f1",
        "required_tool_recall",
        "argument_field_accuracy",
        "argument_exact_call_accuracy",
        "schema_valid_rate",
        "semantic_argument_valid_rate",
        "invalid_call_rate",
        "duplicate_call_rate",
        "unnecessary_call_rate",
        "missing_required_call_rate",
        "execution_success_rate",
        "retry_rate",
    ]
    completed = [item for item in results if item["task_completed"]]
    return {
        "cases": len(results),
        **{field: statistics.fmean(item[field] for item in results) for field in rate_fields},
        "exact_sequence_success_rate": statistics.fmean(
            bool(item["exact_sequence_success"]) for item in results
        ),
        "forbidden_tool_violation_rate": statistics.fmean(
            bool(item["forbidden_tool_violation"]) for item in results
        ),
        "task_completion_rate": len(completed) / len(results),
        "average_tool_calls_per_task": statistics.fmean(item["tool_calls"] for item in results),
        "p50_latency_ms": statistics.median(item["latency_ms"] for item in results),
        "p95_latency_ms": _percentile([item["latency_ms"] for item in results], 0.95),
        "average_tokens_per_task": statistics.fmean(item["tokens"] for item in results),
        "average_cost_per_task": statistics.fmean(item["cost"] for item in results),
        "tokens_per_successful_task": (
            statistics.fmean(item["tokens"] for item in completed) if completed else None
        ),
        "cost_per_successful_task": (
            statistics.fmean(item["cost"] for item in completed) if completed else None
        ),
    }
