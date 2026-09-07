from __future__ import annotations

import difflib
import re


def dedup_key(company: str, title: str, location: str) -> str:
    value = "|".join((company, title, location)).casefold()
    return re.sub(r"[^a-z0-9一-龥]+", "", value)


def similarity(left: dict[str, str], right: dict[str, str]) -> float:
    fields = ("company", "title", "location")
    scores = [
        difflib.SequenceMatcher(
            None, left.get(key, "").casefold(), right.get(key, "").casefold()
        ).ratio()
        for key in fields
    ]
    return round(sum(scores) / len(scores), 3)


def is_probable_duplicate(
    left: dict[str, str], right: dict[str, str], threshold: float = 0.86
) -> bool:
    if (
        left.get("source") == right.get("source")
        and left.get("source_job_id")
        and left.get("source_job_id") == right.get("source_job_id")
    ):
        return True
    if left.get("company", "").casefold() != right.get("company", "").casefold():
        return False
    return similarity(left, right) >= threshold
