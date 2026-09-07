from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.jobs import JobRead


class RecruitmentPlatformRead(BaseModel):
    id: str
    name: str
    enabled: bool = True
    capabilities: dict[str, bool] = Field(default_factory=dict)
    browser_session_required: bool = True


class VisibleRecruitmentJob(BaseModel):
    """Common visible-page payload emitted by a recruitment browser adapter."""

    model_config = ConfigDict(extra="forbid")

    external_job_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20_000)
    job_url: HttpUrl
    location: str | None = Field(default=None, max_length=300)
    company_name: str | None = Field(default=None, max_length=300)
    salary_text: str | None = Field(default=None, max_length=300)
    experience: str | None = Field(default=None, max_length=300)
    education: str | None = Field(default=None, max_length=300)
    requirements: list[str] = Field(default_factory=list, max_length=50)
    skills: list[str] = Field(default_factory=list, max_length=50)
    benefits: list[str] = Field(default_factory=list, max_length=50)
    raw_data: dict[str, Any] = Field(default_factory=dict)


class VisibleRecruitmentImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_url: HttpUrl
    captured_at: datetime | None = None
    jobs: list[VisibleRecruitmentJob] = Field(min_length=1, max_length=100)


class RecruitmentImportResponse(BaseModel):
    platform: str
    collection_mode: str = "visible_page_only"
    page_url: str
    items: list[JobRead]
    created: int
    duplicates: int
    updated: int = 0
    total: int
    safety_notice: str = (
        "仅接收用户当前可见页面的结构化职位字段；不保存 Cookie、密码、Token 或原始页面 HTML。"
    )


class RecruitmentProviderHealthRead(BaseModel):
    platform: str
    status: str
    result_count: int = 0
    cards_found: int = 0
    cards_parsed: int = 0
    parse_failure_count: int = 0
    error_code: str | None = None
    message: str | None = None
    duration_ms: int | None = None


class RecruitmentSearchRequest(BaseModel):
    keyword: str = Field(default="", max_length=200)
    city: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    experience: list[str] = Field(default_factory=list, max_length=20)
    education: list[str] = Field(default_factory=list, max_length=20)
    job_type: list[str] = Field(default_factory=list, max_length=20)
    industry: list[str] = Field(default_factory=list, max_length=20)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    platforms: list[str] = Field(default_factory=list, max_length=10)


class RecruitmentSearchResponse(BaseModel):
    items: list[JobRead]
    total: int
    possible_duplicate_count: int = 0
    platform_status: dict[str, RecruitmentProviderHealthRead] = Field(default_factory=dict)
