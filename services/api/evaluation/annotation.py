"""Human annotation quality checks for binary and categorical labels."""

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
