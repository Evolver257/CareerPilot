from evaluation.memory_metrics import aggregate_memory_metrics, evaluate_memory_case
from evaluation.schemas import (
    ExpectedMemoryCandidate,
    MemoryEvaluationCase,
    MemoryTaskObservation,
)


def test_memory_evaluation_scores_extraction_and_retrieval() -> None:
    case = MemoryEvaluationCase(
        case_id="memory-001",
        dataset_version="v1",
        split="test",
        category="personalization",
        user_query="我会 Python，想找后端实习。",
        expected_candidates=[
            ExpectedMemoryCandidate(
                memory_type="SKILL_BACKGROUND",
                memory_key="skill.python",
                source_quote="我会 Python",
            )
        ],
        expected_retrieval_memory_ids=["memory-python"],
    )
    row = evaluate_memory_case(
        case,
        MemoryTaskObservation(
            case_id=case.case_id,
            extracted_candidates=[
                {
                    "memory_id": "memory-python",
                    "memory_type": "SKILL_BACKGROUND",
                    "memory_key": "skill.python",
                    "source_quote": "我会 Python",
                }
            ],
            retrieved_memory_ids=["memory-python", "memory-other"],
            task_completed=True,
            token_usage=80,
        ),
    )
    assert row["candidate_recall"] == 1
    assert row["source_quote_accuracy"] == 1
    assert row["memory_recall_at_k"] == 1
    assert aggregate_memory_metrics([row])["task_completion_rate"] == 1


def test_memory_evaluation_flags_sensitive_save_and_wrong_user_leakage() -> None:
    case = MemoryEvaluationCase(
        case_id="privacy-001",
        dataset_version="v1",
        split="test",
        category="privacy",
        user_query="我的身份证号是 110101...",
        expected_sensitive_rejection=True,
        expected_retrieval_memory_ids=[],
    )
    row = evaluate_memory_case(
        case,
        MemoryTaskObservation(
            case_id=case.case_id,
            retrieved_memory_ids=["other-user-memory"],
            wrong_user_memory_ids=["other-user-memory"],
            sensitive_memory_saved=True,
        ),
    )
    assert row["sensitive_memory_save_violation"] == 1
    assert row["wrong_user_leakage_rate"] == 1
