"""Deterministic answer/citation evaluation from human or judge claim labels."""

from __future__ import annotations

from collections import Counter
from typing import Any

SUPPORT_STATUSES = {
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNSUPPORTED",
    "CONTRADICTED",
    "NOT_VERIFIABLE",
}


def evaluate_answer(record: dict[str, Any]) -> dict[str, Any]:
    claims = record.get("claims", [])
    invalid = [item for item in claims if item.get("support_status") not in SUPPORT_STATUSES]
    if invalid:
        raise ValueError("Unknown claim support status")
    counts = Counter(item["support_status"] for item in claims)
    weighted_support = counts["SUPPORTED"] + 0.5 * counts["PARTIALLY_SUPPORTED"]
    factual_claims = [item for item in claims if item.get("requires_citation", True)]
    cited_factual = [item for item in factual_claims if item.get("citation_ids")]
    citations = record.get("citations", [])
    correct = sum(
        bool(item.get("exists")) and bool(item.get("supports_claim"))
        for item in citations
    )
    should_refuse = bool(record.get("should_refuse", False))
    did_refuse = bool(record.get("did_refuse", False))
    unsupported = counts["UNSUPPORTED"] + counts["CONTRADICTED"]
    return {
        "case_id": str(record.get("case_id") or ""),
        "category": str(record.get("category") or ""),
        "evaluation_error": record.get("evaluation_error"),
        "faithfulness": weighted_support / len(claims) if claims else 1.0,
        "citation_correctness": correct / len(citations) if citations else 1.0,
        "citation_completeness": (
            len(cited_factual) / len(factual_claims) if factual_claims else 1.0
        ),
        "answer_relevancy": float(record.get("relevant", False)),
        "context_precision": float(record.get("context_precision", 0.0)),
        "context_recall": float(record.get("context_recall", 0.0)),
        "refusal_accuracy": float(should_refuse == did_refuse),
        "false_refusal": float(not should_refuse and did_refuse),
        "unsupported_answer": float(unsupported > 0),
    }
