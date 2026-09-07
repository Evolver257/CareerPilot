from __future__ import annotations

import difflib
import re

from app.job_pipeline.contracts import EvidenceSpan


def _normalized(value: str) -> str:
    return re.sub(r"[^\w+#一-龥]+", "", (value or "").casefold())


def validate_evidence(
    value: str,
    source_text: str,
    *,
    section: str = "other",
    item_index: int | None = None,
) -> EvidenceSpan:
    candidate = (value or "").strip()
    source = source_text or ""
    if not candidate or not source:
        return EvidenceSpan(candidate, "", section, item_index, confidence=0.0, valid=False)
    direct = source.casefold().find(candidate.casefold())
    normalized_candidate = _normalized(candidate)
    normalized_source = _normalized(source)
    if direct >= 0:
        return EvidenceSpan(
            candidate,
            source[max(0, direct - 20) : direct + len(candidate) + 20],
            section,
            item_index,
            direct,
            direct + len(candidate),
            1.0,
            True,
        )
    if normalized_candidate and normalized_candidate in normalized_source:
        return EvidenceSpan(
            candidate,
            candidate,
            section,
            item_index,
            confidence=0.92,
            valid=True,
        )
    score = difflib.SequenceMatcher(
        None, normalized_candidate, normalized_source[: max(len(normalized_candidate) * 3, 80)]
    ).ratio()
    return EvidenceSpan(
        candidate,
        "",
        section,
        item_index,
        confidence=round(score, 3),
        valid=score >= 0.92,
    )
