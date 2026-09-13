import pytest

from evaluation.answer_evaluation import evaluate_answer
from evaluation.metrics import graded_retrieval_metrics
from evaluation.rag_ablation import (
    RAGAblationConfig,
    evaluate_recorded,
    pareto_frontier,
    staged_configs,
)
from evaluation.schemas import RAGEvaluationCase


def test_staged_ablation_is_bounded_and_reproducible() -> None:
    configs = staged_configs()
    assert RAGAblationConfig().chunk_size == 160
    assert RAGAblationConfig().chunk_overlap == 16
    assert 10 < len(configs) < 40
    assert len({item.key() for item in configs}) == len(configs)
    assert RAGAblationConfig().key() == RAGAblationConfig().key()
    assert any(item.dense_weight == 1 and item.sparse_weight == 0 for item in configs)
    assert any(item.dense_weight == 0 and item.sparse_weight == 1 for item in configs)


def test_ablation_rejects_incomparable_or_invalid_retrieval_configuration() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        RAGAblationConfig(dense_weight=0.8, sparse_weight=0.8)
    with pytest.raises(ValueError, match="smaller than chunk_size"):
        RAGAblationConfig(chunk_size=128, chunk_overlap=128)


def test_graded_metrics_penalize_hard_negative() -> None:
    metrics = graded_retrieval_metrics(["gold", "hard"], {"gold": 3, "hard": 0}, ["hard"], k=2)
    assert metrics["recall"] == 1.0
    assert metrics["hard_negative_rejection_rate"] == 0.0
    assert metrics["false_evidence_rate"] == 0.5


def test_answer_metrics_check_claims_citations_and_refusal() -> None:
    metrics = evaluate_answer(
        {
            "claims": [
                {"support_status": "SUPPORTED", "citation_ids": ["c1"]},
                {"support_status": "UNSUPPORTED", "citation_ids": []},
            ],
            "citations": [{"exists": True, "supports_claim": True}],
            "relevant": True,
            "should_refuse": False,
            "did_refuse": False,
        }
    )
    assert metrics["faithfulness"] == 0.5
    assert metrics["citation_completeness"] == 0.5
    assert metrics["unsupported_answer"] == 1.0
    assert metrics["case_id"] == ""


def test_pareto_frontier_excludes_dominated_configuration() -> None:
    results = [
        {
            "config_id": "good",
            "summary": {
                "recall": 1,
                "ndcg": 1,
                "no_answer_accuracy": 1,
                "latency_ms": 10,
                "context_tokens": 100,
            },
        },
        {
            "config_id": "bad",
            "summary": {
                "recall": 0.5,
                "ndcg": 0.5,
                "no_answer_accuracy": 0.5,
                "latency_ms": 20,
                "context_tokens": 200,
            },
        },
    ]
    assert pareto_frontier(results) == ["good"]


def test_ablation_refuses_to_reuse_one_observation_for_every_config() -> None:
    case = RAGEvaluationCase(
        case_id="rag-1",
        dataset_version="v1",
        split="dev",
        topic="skills",
        query="Python skills",
        answerable=True,
        judgments=[{"document_id": "doc-1", "grade": 3}],
    )
    config = RAGAblationConfig()
    with pytest.raises(ValueError, match="must rerun retrieval"):
        evaluate_recorded(
            [case],
            [{"case_id": "rag-1", "retrieved_document_ids": ["doc-1"]}],
            config,
            enforce_config_id=True,
        )
