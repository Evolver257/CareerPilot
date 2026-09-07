from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.job_knowledge import SKILL_ALIASES, canonicalize_skill, normalize_skill_name

_ROLE_FAMILY_RULES = (
    ("AI/LLM", ("agent", "rag", "llm", "大模型", "智能体", "nlp")),
    ("AI算法", ("算法", "机器学习", "深度学习", "计算机视觉", "推荐")),
    ("机器人", ("机器人", "ros", "控制算法", "运动规划")),
    ("后端开发", ("后端", "backend", "server", "服务端")),
    ("前端开发", ("前端", "frontend", "react", "vue")),
    ("数据", ("数据分析", "数据工程", "数仓", "data")),
    ("测试", ("测试", "qa", "质量保障")),
    ("产品", ("产品经理", "产品运营", "product")),
    ("运维/DevOps", ("运维", "devops", "sre")),
)


def _text(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def normalize_title(value: str | None) -> str:
    title = re.sub(r"\s+", " ", _text(value))
    title = re.sub(r"[【\[]?(急招|招聘中|实习招聘)[】\]]?", "", title, flags=re.I)
    return title.strip(" -—|｜")


def normalize_role_family(title: str | None, description: str = "") -> str:
    text = f"{_text(title)} {description}".casefold()
    for family, keywords in _ROLE_FAMILY_RULES:
        if any(keyword.casefold() in text for keyword in keywords):
            return family
    return "其他"


def normalize_location(value: str | None) -> dict[str, str]:
    raw = _text(value)
    if not raw:
        return {"raw": "", "city": "", "district": "", "normalized": ""}
    parts = [part.strip() for part in re.split(r"[·|｜,，/]", raw) if part.strip()]
    if len(parts) == 1:
        spaced = re.match(
            r"^(北京|上海|深圳|广州|武汉|成都|杭州|南京|西安|.+市)\s+(.+)$",
            raw,
        )
        if spaced and spaced.group(2).endswith(("区", "县", "新区", "开发区")):
            parts = [spaced.group(1), spaced.group(2)]
    city = parts[0] if parts else raw
    return {
        "raw": raw,
        "city": city,
        "district": parts[1] if len(parts) > 1 else "",
        "normalized": raw,
    }


def normalize_salary(value: str | None) -> dict[str, Any]:
    raw = _text(value)
    result: dict[str, Any] = {
        "raw": raw,
        "minimum": None,
        "maximum": None,
        "unit": "",
        "currency": "CNY",
        "months": None,
        "confidence": 0.0,
        "status": "unknown",
    }
    if not raw:
        return result
    if re.search(r"面议|negotiable|面谈", raw, re.I):
        result.update(status="negotiable", confidence=1.0)
        return result
    months = re.search(r"(?:·|\s)(\d{1,2})\s*薪", raw, re.I)
    if months:
        result["months"] = int(months.group(1))
    unit_match = re.search(
        r"(小时|时薪|hour|hr|天|日薪|day|月|月薪|年|year|hourly|daily)", raw, re.I
    )
    unit_text = unit_match.group(1).casefold() if unit_match else ""
    if unit_text in {"小时", "时薪", "hour", "hr", "hourly"}:
        unit = "cny_hour"
    elif unit_text in {"天", "日薪", "day", "daily"}:
        unit = "cny_day"
    elif unit_text in {"年", "year"} or re.search(r"万/年|万每年", raw, re.I):
        unit = "cny_year"
    else:
        unit = "cny_month"
    number = r"\d{1,3}(?:\.\d+)?"
    match = re.search(
        rf"(?P<low>{number})\s*(?P<low_unit>[kK千萬万])?\s*"
        rf"(?:[-–—~～至到]|~)\s*(?P<high>{number})\s*"
        rf"(?P<high_unit>[kK千萬万])?",
        raw,
    )
    if match is None:
        match = re.search(rf"(?P<low>{number})\s*(?P<low_unit>[kK千萬万])?", raw)
    if match is None:
        result["status"] = "unparsed"
        return result

    def amount(name: str) -> int:
        value_number = float(match.group(name))
        suffix = (match.group(f"{name}_unit") or "").casefold()
        if not suffix and match.groupdict().get("high_unit"):
            suffix = (match.group("high_unit") or "").casefold()
        if suffix in {"k", "千"}:
            value_number *= 1000
        elif suffix in {"万", "萬"}:
            value_number *= 10000
        return round(value_number)

    low = amount("low")
    high = amount("high") if match.groupdict().get("high") else low
    result.update(minimum=low, maximum=high, unit=unit, confidence=0.95, status="parsed")
    return result


def normalize_education(value: str | None) -> str:
    raw = _text(value)
    if not raw:
        return ""
    if re.search(r"不限|无要求|不作要求", raw):
        return "学历不限"
    for label, patterns in (
        ("博士", ("博士", "phd")),
        ("硕士", ("硕士", "研究生", "master")),
        ("本科", ("本科", "学士", "bachelor")),
        ("大专", ("大专", "专科", "associate")),
        ("中专/高中", ("中专", "高中", "technical secondary")),
    ):
        if any(pattern.casefold() in raw.casefold() for pattern in patterns):
            return label
    return raw


def normalize_experience(value: str | None) -> str:
    raw = _text(value).casefold()
    if not raw:
        return ""
    if re.search(r"不限|无经验|无需经验|应届|在校", raw):
        return "应届/经验不限"
    ranges = re.findall(r"(\d{1,2})\s*(?:-|~|～|至|到)\s*(\d{1,2})\s*年", raw)
    if ranges:
        low = min(int(pair[0]) for pair in ranges)
        high = max(int(pair[1]) for pair in ranges)
    else:
        values = [int(item) for item in re.findall(r"(?<!\d)(\d{1,2})\s*(?:\+|年以上|年)", raw)]
        if not values:
            return ""
        low = high = max(values)
    if low >= 5:
        return "5年以上"
    if low >= 3:
        return "3-5年"
    if high <= 1:
        return "1年以内"
    return "1-3年"


def normalize_employment_type(value: str | None) -> str:
    raw = _text(value)
    lowered = raw.casefold()
    if any(item in lowered for item in ("实习", "intern")):
        return "实习"
    if any(item in lowered for item in ("兼职", "part-time", "part time")):
        return "兼职"
    if any(item in lowered for item in ("全职", "full-time", "full time")):
        return "全职"
    return raw


def normalize_skills(text: str) -> list[dict[str, str]]:
    lowered = normalize_skill_name(text)
    found: dict[str, str] = {}
    for alias, canonical in SKILL_ALIASES.items():
        if alias and alias in lowered:
            found[canonical] = alias
    # Keep common skills that are not part of the legacy taxonomy aliases.
    for skill in ("Kafka", "Linux", "机器学习", "深度学习", "计算机视觉", "强化学习", "NLP"):
        if normalize_skill_name(skill) in lowered:
            found.setdefault(canonicalize_skill(skill), skill)
    return [{"name": name, "matched_text": matched} for name, matched in found.items()]
