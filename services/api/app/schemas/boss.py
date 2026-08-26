from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.jobs import JobRead


class BossVisibleJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_job_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20_000)
    job_url: HttpUrl
    location: str | None = Field(default=None, max_length=300)
    company_name: str | None = Field(default=None, max_length=300)
    salary_text: str | None = Field(default=None, max_length=300)
    tags: list[str] = Field(default_factory=list, max_length=30)
    description_source: Literal["detail_panel", "card_summary"] = "card_summary"


class BossVisibleImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_url: HttpUrl
    captured_at: datetime | None = None
    jobs: list[BossVisibleJob] = Field(min_length=1, max_length=50)


class BossVisibleImportResponse(BaseModel):
    platform: str = "boss"
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
