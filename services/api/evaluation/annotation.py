"""Human annotation quality checks for binary and categorical labels.

V1 uses :func:`cohen_kappa`; RAG V2 additionally needs a weighted score for
the ordered 0/1/2/3 relevance scale and explicit adjudication triggers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable


def agreement_rate(labels_a: list[Hashable], labels_b: list[Hashable]) -> float:
    if len(labels_a) != len(labels_b) or not labels_a:
        raise ValueError("Annotation lists must have the same non-zero length")
    return sum(left == right for left, right in zip(labels_a, labels_b, strict=True)) / len(
        labels_a
    )


def cohen_kappa(labels_a: list[Hashable], labels_b: list[Hashable]) -> float:
    """Compute unweighted Cohen's kappa without adding a heavy dependency."""

    observed = agreement_rate(labels_a, labels_b)
    count_a = Counter(labels_a)
    count_b = Counter(labels_b)
    total = len(labels_a)
    expected = sum(
        (count_a[label] / total) * (count_b[label] / total) for label in count_a | count_b
    )
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def annotation_quality(labels_a: list[Hashable], labels_b: list[Hashable]) -> dict[str, float]:
    return {
        "agreement_rate": agreement_rate(labels_a, labels_b),
        "cohen_kappa": cohen_kappa(labels_a, labels_b),
    }


def weighted_cohen_kappa(
    labels_a: list[int], labels_b: list[int], *, quadratic: bool = False
) -> float:
    """Compute linear or quadratic weighted Cohen's kappa.

    The labels are relevance grades, so disagreement between 3 and 2 is less
    severe than disagreement between 3 and 0.  ``quadratic=False`` is the
    conservative default used by the V2 stability gate.
    """

    if len(labels_a) != len(labels_b) or not labels_a:
        raise ValueError("Annotation lists must have the same non-zero length")
    categories = sorted(set(labels_a) | set(labels_b))
    if len(categories) == 1:
        return 1.0
    low, high = min(categories), max(categories)
    span = max(high - low, 1)

    def weight(left: int, right: int) -> float:
        distance = abs(left - right) / span
        return distance * distance if quadratic else distance

    observed = sum(weight(left, right) for left, right in zip(labels_a, labels_b, strict=True)) / len(labels_a)
    total = len(labels_a)
    count_a, count_b = Counter(labels_a), Counter(labels_b)
    expected = sum(
        (count_a[left] / total) * (count_b[right] / total) * weight(left, right)
        for left in categories
        for right in categories
    )
    if expected == 0:
        return 1.0 if observed == 0 else 0.0
    return 1 - observed / expected


def requires_adjudication(
    label_a: int,
    label_b: int,
    *,
    answerability_a: str | None = None,
    answerability_b: str | None = None,
    hard_constraint_a: str | None = None,
    hard_constraint_b: str | None = None,
) -> bool:
    """Return whether a query/job pair must go to the adjudicator."""

    return (
        abs(label_a - label_b) >= 2
        or ({label_a, label_b} <= {0, 2, 3} and 0 in {label_a, label_b} and max(label_a, label_b) >= 2)
        or answerability_a != answerability_b
        or hard_constraint_a != hard_constraint_b
    )
