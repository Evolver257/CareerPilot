import json
from pathlib import Path

import pytest

from evaluation.annotation import annotation_quality, cohen_kappa
from evaluation.metrics import answer_metrics, context_metrics, retrieval_metrics
from evaluation.run_agent_eval import run
from evaluation.schemas import (
    ExpectedToolCall,
    ObservedToolCall,
    ToolEvaluationCase,
    ToolTaskObservation,
    assert_gold_ready,
)
from evaluation.tool_metrics import aggregate_tool_metrics, evaluate_tool_task


def _case(**updates):
    values = {
        "case_id": "case-1",
        "dataset_version": "v1",
        "split": "test",
        "category": "multi_tool",
        "user_query": "找北京的 AI 岗位并排序",
        "expected_calls": [
            ExpectedToolCall(
                tool_name="search_jobs",
                arguments={"cities": ["北京"], "keywords": ["AI"]},
            ),
            ExpectedToolCall(tool_name="rank_jobs", arguments={"final_top_k": 5}),
            ExpectedToolCall(tool_name="queue_application", forbidden=True, required=False),
        ],
    }
    values.update(updates)
    return ToolEvaluationCase(**values)


def test_tool_metrics_measure_selection_arguments_sequence_and_forbidden_calls():
    observation = ToolTaskObservation(
        case_id="case-1",
        task_completed=True,
        total_latency_ms=120,
        calls=[
            ObservedToolCall(
                call_id="1",
                tool_name="search_jobs",
                arguments={"cities": ["北京"], "keywords": ["AI"], "limit": 20},
                schema_valid=True,
                semantically_valid=True,
                latency_ms=50,
                prompt_tokens=10,
            ),
            ObservedToolCall(
                call_id="2",
                tool_name="rank_jobs",
                arguments={"final_top_k": 5, "job_ids": ["a"]},
                schema_valid=True,
                semantically_valid=True,
                latency_ms=70,
                prompt_tokens=20,
                completion_tokens=5,
                cost=0.02,
            ),
        ],
    )
    result = evaluate_tool_task(_case(), observation)

    assert result["tool_selection_f1"] == 1
    assert result["argument_field_accuracy"] == 1
    assert result["exact_sequence_success"] is True
    assert result["forbidden_tool_violation"] is False
    assert result["tokens"] == 35
    assert result["cost_per_success"] == 0.02


def test_tool_metrics_count_missing_extra_duplicate_and_forbidden_calls():
    calls = [
        ObservedToolCall(call_id="1", tool_name="search_jobs", arguments={"cities": ["上海"]}),
        ObservedToolCall(call_id="2", tool_name="search_jobs", arguments={"cities": ["上海"]}),
        ObservedToolCall(call_id="3", tool_name="queue_application", arguments={}),
    ]
    result = evaluate_tool_task(
        _case(), ToolTaskObservation(case_id="case-1", calls=calls, task_completed=False)
    )

    assert result["argument_field_accuracy"] == 0
    assert result["missing_required_call_rate"] == 0.5
    assert result["duplicate_call_rate"] > 0
    assert result["unnecessary_call_rate"] > 0
    assert result["forbidden_tool_violation"] is True


def test_aggregate_metrics_include_completion_latency_and_cost():
    first = evaluate_tool_task(
        _case(),
        ToolTaskObservation(case_id="case-1", task_completed=True, total_latency_ms=100),
    )
    second = evaluate_tool_task(
        _case(case_id="case-2"),
        ToolTaskObservation(case_id="case-2", task_completed=False, total_latency_ms=300),
    )
    summary = aggregate_tool_metrics([first, second])

    assert summary["cases"] == 2
    assert summary["task_completion_rate"] == 0.5
    assert summary["p50_latency_ms"] == 200
    assert summary["p95_latency_ms"] == 300


def test_annotation_quality_and_gold_guard():
    quality = annotation_quality([1, 1, 0, 0], [1, 0, 0, 0])
    assert quality["agreement_rate"] == 0.75
    assert -1 <= quality["cohen_kappa"] <= 1
    assert cohen_kappa([1, 1], [1, 1]) == 1
    with pytest.raises(ValueError, match="not adjudicated gold"):
        assert_gold_ready([_case()])

    gold = _case(
        annotation_status="adjudicated_gold",
        annotators=["reviewer-a", "reviewer-b"],
        adjudicated_by="reviewer-c",
    )
    assert_gold_ready([gold])


def test_extended_rag_and_answer_metrics():
    base = retrieval_metrics(["a", "x"], ["a", "b"], k=2)
    assert base["precision"] == 0.5
    assert base["hit_rate"] == 1
    context = context_metrics(["a", "hard"], ["a", "b"], ["hard"], k=2)
    assert context["context_precision"] == 0.5
    assert context["context_recall"] == 0.5
    assert context["hard_negative_rejection_rate"] == 0
    no_answer = context_metrics([], [], ["hard"])
    assert no_answer["no_answer_retrieval_accuracy"] == 1

    answer = answer_metrics(
        supported_claims=3,
        total_claims=4,
        correct_citations=2,
        total_citations=2,
        relevant_answer=True,
        should_refuse=True,
        did_refuse=True,
    )
    assert answer == {
        "faithfulness": 0.75,
        "citation_correctness": 1,
        "answer_relevancy": 1.0,
        "refusal_accuracy": 1.0,
    }


def test_runner_never_overwrites_and_counts_missing_observations(tmp_path: Path):
    dataset = tmp_path / "dataset.jsonl"
    observations = tmp_path / "observations.jsonl"
    dataset.write_text(_case().model_dump_json() + "\n", encoding="utf-8")
    observations.write_text(
        ToolTaskObservation(case_id="case-1", task_completed=True).model_dump_json() + "\n",
        encoding="utf-8",
    )

    output, summary = run(dataset, observations, tmp_path / "runs", require_gold=False, seed=7)

    assert summary["cases"] == 1
    assert (output / "manifest.json").exists()
    assert json.loads((output / "manifest.json").read_text(encoding="utf-8"))["seed"] == 7
    assert "not a human-gold" in (output / "report.md").read_text(encoding="utf-8")
