import pytest

from evaluation.cases import cases
from evaluation.metrics import retrieval_metrics, validate_labels


def test_metrics_deduplicate_and_exclude_unanswerable_from_recall():
    result = retrieval_metrics(["a", "a", "x", "b"], ["a", "b"], k=3)
    assert result["recall"] == 1
    assert result["mrr"] == 1
    assert 0 < result["ndcg"] < 1
    assert retrieval_metrics(["a"], [])["recall"] is None
    assert retrieval_metrics([], ["a"])["ndcg"] == 0


def test_topics_never_leak_between_splits():
    questions = cases()
    assert len(questions) == 80
    assert len({q["id"] for q in questions}) == 80
    dev = {q["topic"] for q in questions if q["split"] == "dev"}
    test = {q["topic"] for q in questions if q["split"] == "test"}
    assert not dev & test
    assert all(q["label_status"] == "silver_requires_review" for q in questions)


async def test_local_semantics_never_silently_falls_back(monkeypatch):
    from app.llm.local_semantic import LocalSemanticProvider
    from app.llm.provider import LLMProviderError

    monkeypatch.setattr(
        "app.llm.local_semantic.embedding_model",
        lambda *args: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    with pytest.raises(LLMProviderError, match="Hash"):
        await LocalSemanticProvider().embed("test")


def test_external_labels_are_validated():
    query = {
        "id": "a",
        "topic": "rag",
        "split": "test",
        "relevance": [{"job_id": "j1", "grade": 0}],
    }
    validate_labels([query], {"j1"})
    with pytest.raises(ValueError, match="Foreign"):
        validate_labels([query], {"other"})
    with pytest.raises(ValueError, match="Duplicate"):
        validate_labels([query, query], {"j1"})
    with pytest.raises(ValueError, match="leaks"):
        validate_labels([query, {**query, "id": "b", "split": "dev"}], {"j1"})
