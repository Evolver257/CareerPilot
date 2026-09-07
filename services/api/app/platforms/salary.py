from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SalaryRange:
    text: str
    minimum: int | None
    maximum: int | None
    months: int | None = None


_NUMBER = r"\d+(?:\.\d+)?"


def parse_salary_text(value: str | None) -> SalaryRange:
    text = " ".join((value or "").split())
    if not text:
        return SalaryRange("", None, None)
    months_match = re.search(r"(?:·|/|每年)?\s*(\d{1,2})\s*薪", text, re.IGNORECASE)
    months = int(months_match.group(1)) if months_match else None
    if re.search(r"面议|negotiable|面谈", text, re.IGNORECASE):
        return SalaryRange(text, None, None, months)

    range_match = re.search(
        rf"(?P<first>{_NUMBER})\s*(?P<unit1>[Kk千]?|万)?\s*(?:-|~|至|—|–)\s*"
        rf"(?P<second>{_NUMBER})\s*(?P<unit2>[Kk千]?|万)?",
        text,
    )
    if not range_match:
        range_match = re.search(rf"(?P<first>{_NUMBER})\s*(?P<unit1>[Kk千]?|万)?", text)
    if not range_match:
        return SalaryRange(text, None, None, months)

    unit1 = range_match.groupdict().get("unit1") or _unit_after(
        range_match.end("first"), text
    )
    second = range_match.groupdict().get("second")
    unit2 = (
        range_match.groupdict().get("unit2")
        or _unit_after(range_match.end("second"), text)
        if second is not None
        else None
    )
    unit1 = unit1 or unit2
    minimum = _to_yuan(float(range_match.group("first")), unit1, text)
    if second is not None:
        maximum = _to_yuan(float(second), unit2 or unit1, text)
    else:
        maximum = minimum
    return SalaryRange(text, minimum, maximum, months)


def _unit_after(position: int, text: str) -> str | None:
    tail = text[position:].lstrip()
    if tail and tail[0] in {"K", "k", "千", "万"}:
        return tail[0]
    return None


def _to_yuan(number: float, unit: str | None, text: str) -> int:
    normalized_unit = (unit or "").casefold()
    if normalized_unit in {"k", "千"}:
        number *= 1000
    elif normalized_unit == "万":
        number *= 10000
    elif "元/天" in text or "元/日" in text:
        # Preserve the source unit in the numeric fields. Existing CareerPilot
        # matching treats day-rate jobs as a separate display convention.
        pass
    return int(round(number))
