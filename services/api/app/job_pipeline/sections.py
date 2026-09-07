from __future__ import annotations

import re

from app.job_pipeline.contracts import SectionItem

_ALIASES = {
    "responsibilities": ("岗位职责", "工作职责", "职位职责", "工作内容", "主要职责", "你将负责"),
    "requirements": (
        "任职要求",
        "任职条件",
        "职位要求",
        "岗位要求",
        "资格要求",
        "岗位资格",
        "招聘条件",
    ),
    "preferred": ("加分项", "优先条件", "加分条件", "优先资格", "nice to have", "bonus points"),
    "benefits": ("福利待遇", "岗位福利", "公司福利", "你将获得", "福利"),
    "summary": ("职位简介", "岗位简介", "职位描述", "岗位描述", "岗位概览", "about the role"),
}


def _heading(line: str) -> str | None:
    value = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip()
    value = re.sub(r"^(?:[一二三四五六七八九十百]+|\d{1,2})\s*[、.．)]\s*", "", value)
    value = re.sub(r"^[【\[（(]\s*|[】\]）)]\s*$", "", value)
    value = value.strip(" ：:|-—")
    normalized = re.sub(r"\s+", " ", value.casefold())
    for section, aliases in _ALIASES.items():
        if normalized in {alias.casefold() for alias in aliases}:
            return section
        if any(
            normalized.startswith(alias.casefold() + suffix)
            for alias in aliases
            for suffix in (" ", ":", "：", "|", "｜")
        ):
            return section
    return None


def parse_sections(text: str) -> dict[str, list[SectionItem]]:
    sections: dict[str, list[SectionItem]] = {key: [] for key in (*_ALIASES, "other")}
    current = "other"
    counters = {key: 0 for key in sections}
    for line_index, raw_line in enumerate((text or "").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        section = _heading(line)
        if section:
            current = section
            remainder = (
                re.sub(r"^.*?(?:：|:|\||｜)\s*", "", line) if re.search(r"[：:|｜]", line) else ""
            )
            if remainder and remainder != line and _heading(remainder) != section:
                sections[current].append(
                    SectionItem(remainder, current, counters[current], line_index)
                )
                counters[current] += 1
            continue
        # Split only list-like separators. Do not split normal prose at commas.
        values = re.split(
            r"\n+|(?<=；)|(?<=[。！？])\s+(?=[一二三四五六七八九十百\d]+[、.)])", line
        )
        for value in values:
            value = re.sub(
                r"^\s*(?:[-*•·]|\d{1,2}[、.)]|[一二三四五六七八九十百]+[、.])\s*", "", value
            ).strip()
            if value:
                sections[current].append(SectionItem(value, current, counters[current], line_index))
                counters[current] += 1
    return {key: items for key, items in sections.items() if items}
