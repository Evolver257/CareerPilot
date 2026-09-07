from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class JobReference:
    """Platform-owned identity kept separate from CareerPilot's UUID."""

    platform: str
    external_job_id: str
    source_url: str
    platform_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JobSearchQuery:
    keyword: str = ""
    city: str | None = None
    district: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    experience: tuple[str, ...] = ()
    education: tuple[str, ...] = ()
    job_type: tuple[str, ...] = ()
    industry: tuple[str, ...] = ()
    page: int = 1
    page_size: int = 20
    platforms: tuple[str, ...] = ()

    @property
    def normalized_platforms(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.strip().casefold() for item in self.platforms if item.strip()
            )
        )


@dataclass(frozen=True)
class ProviderCapabilities:
    keyword: bool = True
    city: bool = True
    district: bool = False
    salary: bool = False
    experience: bool = False
    education: bool = False
    job_type: bool = False
    industry: bool = False
    search: bool = True
    detail: bool = True
    browser_session_required: bool = True


@dataclass(frozen=True)
class NormalizedJob:
    platform: str
    external_job_id: str
    source_url: str
    title: str
    id: UUID | None = None
    company_name: str | None = None
    company_id: str | None = None
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_months: int | None = None
    city: str | None = None
    district: str | None = None
    location: str | None = None
    experience: str | None = None
    education: str | None = None
    job_type: str | None = None
    description: str = ""
    requirements: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    benefits: tuple[str, ...] = ()
    company_industry: str | None = None
    company_size: str | None = None
    company_stage: str | None = None
    recruiter_name: str | None = None
    recruiter_title: str | None = None
    publish_time: datetime | None = None
    crawled_at: datetime | None = None
    raw_data: Mapping[str, Any] = field(default_factory=dict)
    platform_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    platform: str
    status: str
    result_count: int = 0
    cards_found: int = 0
    cards_parsed: int = 0
    parse_failure_count: int = 0
    error_code: str | None = None
    message: str | None = None
    duration_ms: int | None = None


@dataclass(frozen=True)
class ProviderSearchResult:
    jobs: tuple[NormalizedJob, ...]
    health: ProviderHealth


class RecruitmentProvider(Protocol):
    name: str
    label: str
    capabilities: ProviderCapabilities

    def can_handle_url(self, url: str) -> bool: ...

    def extract_job_reference(self, url: str) -> JobReference: ...

    def parse_search_result(self, raw_data: Any, *, page_url: str) -> list[NormalizedJob]: ...

    def parse_job_detail(
        self, raw_data: Any, *, reference: JobReference
    ) -> NormalizedJob: ...

    async def search_jobs(self, query: JobSearchQuery) -> ProviderSearchResult: ...

    async def get_job_detail(self, reference: JobReference) -> NormalizedJob | None: ...
