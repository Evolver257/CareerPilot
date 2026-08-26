from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

from app.platforms.base import UnknownStateError


@dataclass(frozen=True)
class BossVisibleJob:
    external_job_id: str
    title: str
    description: str
    source_url: str
    location: str | None = None
    company_name: str | None = None
    salary_text: str | None = None


@dataclass
class _Card:
    depth: int
    external_job_id: str | None
    source_url: str | None
    fields: dict[str, list[str]]


class _BossListParser(HTMLParser):
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
        job_id = attributes.get("data-jobid") or attributes.get("data-job-id")
        is_card = bool(
            classes.intersection(
                {"job-card-wrap", "job-card-wrapper", "job-card-box", "card-area", "job-card"}
            )
            or job_id
        )
        if self.current is None and is_card:
            href = attributes.get("href")
            self.current = _Card(self.depth, job_id, href, {})
        if self.current is None:
            return
        field = self._field_for(classes, tag, attributes)
        if field:
            self.active.append((field, self.depth))
        if self.current.source_url is None and tag == "a":
            href = attributes.get("href") or ""
            if "/job_detail/" in href:
                self.current.source_url = href
                self.current.external_job_id = (
                    self.current.external_job_id or self._id_from_href(href)
                )

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        for field, _ in self.active:
            self.current.fields.setdefault(field, []).append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is not None:
            self.active = [(field, depth) for field, depth in self.active if depth != self.depth]
            if self.depth == self.current.depth:
                self.cards.append(self.current)
                self.current = None
                self.active = []
        self.depth = max(0, self.depth - 1)

    @staticmethod
    def _field_for(classes: set[str], tag: str, attrs: dict[str, str | None]) -> str | None:
        if "job-name" in classes or "data-job-title" in attrs:
            return "title"
        if "job-title" in classes and tag in {"a", "span", "h1", "h2", "h3"}:
            return "title"
        if classes.intersection(
            {"boss-name", "company-name", "company-text", "company-info"}
        ):
            return "company"
        if classes.intersection(
            {"company-location", "job-area", "job-location", "job-card-location"}
        ):
            return "location"
        if classes.intersection({"salary", "job-salary", "job-card-salary"}):
            return "salary"
        if classes.intersection({"job-card-left", "job-sec-text", "job-detail", "detail-content"}):
            return "description"
        return None

    @staticmethod
    def _id_from_href(href: str) -> str | None:
        match = re.search(r"/job_detail/([^./?]+)", href)
        return match.group(1) if match else None


def _clean(values: list[str]) -> str:
    return " ".join("".join(values).split())


def parse_job_list(html: str, *, page_url: str) -> list[BossVisibleJob]:
    parser = _BossListParser()
    parser.feed(html)
    jobs: list[BossVisibleJob] = []
    for card in parser.cards:
        external_job_id = card.external_job_id
        title = _clean(card.fields.get("title", []))
        source_url = card.source_url or page_url
        if not external_job_id or not title:
            continue
        description = _clean(card.fields.get("description", [])) or title
        jobs.append(
            BossVisibleJob(
                external_job_id=external_job_id,
                title=title,
                description=description,
                source_url=source_url,
                location=_clean(card.fields.get("location", [])) or None,
                company_name=_clean(card.fields.get("company", [])) or None,
                salary_text=_clean(card.fields.get("salary", [])) or None,
            )
        )
    if not jobs and html.strip():
        raise UnknownStateError("BOSS job cards were not recognized safely")
    return jobs
