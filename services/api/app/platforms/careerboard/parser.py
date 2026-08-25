from __future__ import annotations

from html.parser import HTMLParser
from uuid import UUID

from app.platforms.base import PlatformJob, UnknownStateError


class _CareerBoardFieldParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.active_field: str | None = None
        self.active_depth = 0
        self.fields: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attributes = dict(attrs)
        field = attributes.get("data-cp-field")
        if field and self.active_field is None:
            self.active_field = field
            self.active_depth = self.depth
            self.fields.setdefault(field, [])

    def handle_data(self, data: str) -> None:
        if self.active_field:
            self.fields[self.active_field].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.active_field and self.depth == self.active_depth:
            self.active_field = None
            self.active_depth = 0
        self.depth = max(0, self.depth - 1)


def parse_job_detail(html: str, *, job_id: UUID, platform: str = "careerboard") -> PlatformJob:
    parser = _CareerBoardFieldParser()
    parser.feed(html)
    title = " ".join("".join(parser.fields.get("job-title", [])).split())
    location = " ".join("".join(parser.fields.get("location", [])).split()) or None
    description = " ".join("".join(parser.fields.get("description", [])).split())
    if not title:
        raise UnknownStateError("CareerBoard job title is missing from the page")
    return PlatformJob(
        id=job_id,
        title=title,
        location=location,
        description=description,
        platform=platform,
    )
