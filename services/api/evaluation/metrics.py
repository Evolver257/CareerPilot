import math


def validate_labels(questions, corpus_ids):
    """Reject foreign IDs, duplicate judgments, and topic leakage before a run."""
    seen, topics = set(), {}
    if not questions:
        raise ValueError("Empty evaluation set")
    for question in questions:
        if question["id"] in seen:
            raise ValueError("Duplicate question ID")
        seen.add(question["id"])
        if question["split"] not in {"dev", "test"}:
            raise ValueError("Unknown split")
        topic = question["topic"]
        if topics.setdefault(topic, question["split"]) != question["split"]:
            raise ValueError("Topic leaks between dev and test")
        jobs = set()
        for label in question["relevance"]:
            if label["job_id"] not in corpus_ids or label["job_id"] in jobs:
                raise ValueError("Foreign or duplicate job judgment")
            if label["grade"] not in {0, 1}:
                raise ValueError("This benchmark uses binary relevance grades 0/1")
            jobs.add(label["job_id"])


def retrieval_metrics(ids, relevant, k=5):
    ids = list(dict.fromkeys(ids))[:k]
    relevant = set(relevant)
    if not relevant:
        return {
            "precision": None,
            "recall": None,
            "hit_rate": None,
            "ndcg": None,
            "mrr": None,
            "returned_any": bool(ids),
        }
    hits = [int(item in relevant) for item in ids]
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return {
        "precision": sum(hits) / len(ids) if ids else 0,
        "recall": sum(hits) / len(relevant),
        "hit_rate": float(any(hits)),
        "ndcg": sum(hit / math.log2(i + 2) for i, hit in enumerate(hits)) / ideal,
        "mrr": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0),
        "returned_any": bool(ids),
    }


def context_metrics(retrieved, relevant, hard_negatives=(), k=5):
    """Evaluate evidence retrieval, including hard-negative rejection.

    ``retrieved`` is ordered and deduplicated here so chunk fan-out cannot
    inflate the score.  Unanswerable questions are evaluated separately from
    recall-based answerable questions.
    """

    ids = list(dict.fromkeys(retrieved))[:k]
    relevant_set = set(relevant)
    hard_negative_set = set(hard_negatives)
    if not relevant_set:
        return {
            "context_precision": None,
            "context_recall": None,
            "hit_rate": None,
            "hard_negative_rejection_rate": (
                1 - sum(item in hard_negative_set for item in ids) / len(hard_negative_set)
                if hard_negative_set
                else 1.0
            ),
            "no_answer_retrieval_accuracy": float(not ids),
        }
    hits = sum(item in relevant_set for item in ids)
    hard_negative_hits = sum(item in hard_negative_set for item in ids)
    return {
        "context_precision": hits / len(ids) if ids else 0.0,
        "context_recall": hits / len(relevant_set),
        "hit_rate": float(hits > 0),
        "hard_negative_rejection_rate": (
            1 - hard_negative_hits / len(hard_negative_set) if hard_negative_set else 1.0
        ),
        "no_answer_retrieval_accuracy": None,
    }


def answer_metrics(
    *,
    supported_claims: int,
    total_claims: int,
    correct_citations: int,
    total_citations: int,
    relevant_answer: bool,
    should_refuse: bool,
    did_refuse: bool,
):
    """Aggregate externally judged answer labels without pretending to judge with rules."""

    if supported_claims < 0 or total_claims < supported_claims:
        raise ValueError("Invalid supported claim counts")
    if correct_citations < 0 or total_citations < correct_citations:
        raise ValueError("Invalid citation counts")
    return {
        "faithfulness": supported_claims / total_claims if total_claims else 1.0,
        "citation_correctness": (correct_citations / total_citations if total_citations else 1.0),
        "answer_relevancy": float(relevant_answer),
        "refusal_accuracy": float(should_refuse == did_refuse),
    }


def graded_retrieval_metrics(ids, grades, hard_negatives=(), k=10):
    """Graded IR metrics plus explicit false-evidence/no-answer signals."""

    ranked = list(dict.fromkeys(ids))[:k]
    grade_by_id = {str(key): int(value) for key, value in grades.items()}
    relevant = {key for key, grade in grade_by_id.items() if grade > 0}
    hard = {str(value) for value in hard_negatives}
    binary = retrieval_metrics(ranked, relevant, k=k)
    dcg = sum(
        (2 ** grade_by_id.get(item, 0) - 1) / math.log2(index + 2)
        for index, item in enumerate(ranked)
    )
    ideal_grades = sorted(grade_by_id.values(), reverse=True)[:k]
    ideal = sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(ideal_grades))
    return {
        **binary,
        "ndcg": dcg / ideal if ideal else None,
        "context_precision": (
            sum(item in relevant for item in ranked) / len(ranked) if ranked else 0.0
        ),
        "context_recall": (
            sum(item in relevant for item in ranked) / len(relevant) if relevant else None
        ),
        "hard_negative_rejection_rate": (
            1 - sum(item in hard for item in ranked) / len(hard) if hard else 1.0
        ),
        "false_evidence_rate": (
            sum(item in hard or grade_by_id.get(item, 0) == 0 for item in ranked) / len(ranked)
            if ranked
            else 0.0
        ),
    }
