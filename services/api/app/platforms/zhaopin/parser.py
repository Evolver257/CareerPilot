from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from app.platforms.base import ProviderErrorCode, RecruitmentProviderError


@dataclass(frozen=True)
class ZhaopinRawJob:
    external_job_id: str
    title: str
    source_url: str
    company_name: str | None = None
    salary_text: str | None = None
    location: str | None = None
    experience: str | None = None
    education: str | None = None
    description: str = ""
    requirements: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    benefits: tuple[str, ...] = ()
    raw_data: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class _Card:
    depth: int
    external_job_id: str | None
    source_url: str | None
    fields: dict[str, list[str]] = field(default_factory=dict)


class _ZhaopinHtmlParser(HTMLParser):
    card_tokens = {
        "joblist-box",
        "job-list-item",
        "job-card",
        "job-item",
        "position-item",
        "search-result-item",
    }
    field_tokens = {
        "title": {"job-title", "job-name", "position-name", "position-title"},
        "company": {"company-name", "company", "com-name", "companytitle"},
        "salary": {"salary", "job-salary", "sal", "salary-text"},
        "location": {"job-location", "location", "work-location", "city"},
        "experience": {"experience", "work-years", "experience-requirement"},
        "education": {"education", "degree", "education-requirement"},
        "description": {
            "job-desc",
            "job-description",
            "job-detail",
            "description",
            "job-content",
            "responsibility",
        },
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.current: _Card | None = None
        self.active: list[tuple[str, int]] = []
        self.cards: list[_Card] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        external_id = _external_id(attributes)
        is_card = bool(external_id or classes.intersection(self.card_tokens))
        if (
            self.current is not None
            and self.depth > self.current.depth
            and is_card
            and self.current.external_job_id is None
        ):
            # Some SPA versions use joblist-box as a list wrapper and put the
            # actual item cards below it. Promote the nested card instead of
            # treating the entire result list as one job.
            self.current = _Card(
                depth=self.depth,
                external_job_id=external_id,
                source_url=attributes.get("href"),
            )
            self.active = []
        if self.current is None and is_card:
            self.current = _Card(
                depth=self.depth,
                external_job_id=external_id,
                source_url=attributes.get("href"),
            )
        if self.current is None:
            return
        if self.current.source_url is None and tag == "a":
            href = attributes.get("href") or ""
            if _looks_like_job_url(href):
                self.current.source_url = href
                self.current.external_job_id = self.current.external_job_id or _id_from_href(href)
        for field_name, tokens in self.field_tokens.items():
            if classes.intersection(tokens) or attributes.get(f"data-{field_name}") is not None:
                self.active.append((field_name, self.depth))

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        for field_name, _ in self.active:
            self.current.fields.setdefault(field_name, []).append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is not None:
            self.active = [item for item in self.active if item[1] != self.depth]
            if self.depth == self.current.depth:
                self.cards.append(self.current)
                self.current = None
                self.active = []
        self.depth = max(0, self.depth - 1)


def parse_zhaopin_payload(raw_data: Any, *, page_url: str) -> list[ZhaopinRawJob]:
    if isinstance(raw_data, Mapping):
        structured = _mapping_items(raw_data)
        if structured:
            return [_from_mapping(item, page_url=page_url) for item in structured]
        raise _parser_error("搜索结果 JSON 中没有职位数组", stage="search")
    if isinstance(raw_data, list):
        items = [item for item in raw_data if isinstance(item, Mapping)]
        return [_from_mapping(item, page_url=page_url) for item in items]
    if not isinstance(raw_data, str):
        raise _parser_error("智联搜索结果数据类型不可识别", stage="search")
    stripped = raw_data.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return parse_zhaopin_payload(json.loads(stripped), page_url=page_url)
        except json.JSONDecodeError as exc:
            raise _parser_error("智联结构化数据不是有效 JSON", stage="search") from exc

    parser = _ZhaopinHtmlParser()
    parser.feed(raw_data)
    jobs: list[ZhaopinRawJob] = []
    for card in parser.cards:
        title = _clean(card.fields.get("title", []))
        external_id = card.external_job_id
        source_url = urljoin(page_url, card.source_url or "")
        if not external_id and source_url != page_url:
            external_id = _id_from_href(source_url)
        if not title or not external_id:
            continue
        jobs.append(
            ZhaopinRawJob(
                external_job_id=external_id,
                title=title,
                source_url=source_url,
                company_name=_optional(card.fields.get("company")),
                salary_text=_optional(card.fields.get("salary")),
                location=_optional(card.fields.get("location")),
                experience=_optional(card.fields.get("experience")),
                education=_optional(card.fields.get("education")),
                description=_clean(card.fields.get("description", [])) or title,
            )
        )
    if not jobs and raw_data.strip():
        raise _parser_error(
            "智联搜索结果未识别到职位卡片，请确认页面已加载并完成登录或验证",
            stage="search",
        )
    return jobs


def _mapping_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("jobs", "items", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        if isinstance(value, Mapping):
            nested = _mapping_items(value)
            if nested:
                return nested
    if any(
        key in payload
        for key in ("id", "jobId", "positionId", "jobName", "positionName", "title")
    ):
        return [payload]
    return []


def _from_mapping(item: Mapping[str, Any], *, page_url: str) -> ZhaopinRawJob:
    external_id = _first(item, "external_job_id", "externalJobId", "jobId", "positionId", "id")
    title = _first(item, "title", "jobName", "positionName", "name")
    if not external_id:
        raise _parser_error("智联职位缺少 external_job_id", stage="search", field="external_job_id")
    if not title:
        raise _parser_error("智联职位缺少标题", stage="search", field="title")
    source_url = urljoin(
        page_url,
        _first(item, "source_url", "sourceUrl", "url", "jobUrl", "job_url") or page_url,
    )
    description = _first(item, "description", "jobDescription", "detail", "jd") or title
    requirements = _to_tuple(item.get("requirements"))
    skills = _to_tuple(item.get("skills"))
    benefits = _to_tuple(item.get("benefits"))
    return ZhaopinRawJob(
        external_job_id=external_id,
        title=title,
        source_url=source_url,
        company_name=_first(item, "company_name", "companyName", "company", "comName"),
        salary_text=_first(item, "salary_text", "salaryText", "salary"),
        location=_first(item, "location", "workLocation", "city"),
        experience=_first(item, "experience", "experienceRequirement", "workYears"),
        education=_first(item, "education", "educationRequirement", "degree"),
        description=description,
        requirements=requirements,
        skills=skills,
        benefits=benefits,
        raw_data=dict(item),
    )


def _external_id(attributes: Mapping[str, str | None]) -> str | None:
    for key in ("data-job-id", "data-position-id", "data-zwid", "data-id", "jobid", "positionid"):
        value = attributes.get(key)
        if value:
            return value.strip()
    return None


def _looks_like_job_url(value: str) -> bool:
    return bool(re.search(r"job|position|detail|zw", value, re.IGNORECASE))


def _id_from_href(value: str) -> str | None:
    match = re.search(r"(?:jobdetail|job|position|zw)/([^/?#.;]+)", value, re.IGNORECASE)
    return match.group(1) if match else None


def _first(item: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str | int | float) and str(value).strip():
            return str(value).strip()
    return None


def _to_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _clean(values: list[str]) -> str:
    return " ".join("".join(values).split())


def _optional(values: list[str] | None) -> str | None:
    text = _clean(values or [])
    return text or None


def _parser_error(
    message: str, *, stage: str, field: str | None = None
) -> RecruitmentProviderError:
    return RecruitmentProviderError(
        "zhaopin",
        ProviderErrorCode.PARSER_FAILED,
        message,
        parser_stage=stage,
        field=field,
    )
