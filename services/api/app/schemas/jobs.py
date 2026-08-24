from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class JobCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=100)
    external_job_id: str | None = Field(default=None, max_length=300)
    company_id: UUID | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1)
    location: str | None = Field(default=None, max_length=300)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    job_type: str | None = Field(default=None, max_length=100)
    education_requirement: str | None = Field(default=None, max_length=500)
    experience_requirement: str | None = Field(default=None, max_length=500)
    publish_time: datetime | None = None
    source_url: HttpUrl | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    normalized_data: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = Field(default=None, max_length=128)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    external_job_id: str | None
    company_id: UUID | None
    title: str
    description: str
    location: str | None
    salary_min: int | None
    salary_max: int | None
    job_type: str | None
    education_requirement: str | None
    experience_requirement: str | None
    publish_time: datetime | None
    source_url: str | None
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any]
    content_hash: str | None
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    items: list[JobRead]
    total: int
    page: int
    page_size: int
