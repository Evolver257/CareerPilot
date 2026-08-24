from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.jobs import JobRead


class JobSalary(BaseModel):
    minimum: int | None = None
    maximum: int | None = None
    currency: str = ""


class JobRequirements(BaseModel):
    education: str = ""
    experience: str = ""
    responsibilities: list[str] = Field(default_factory=list)


class StructuredJob(BaseModel):
    title: str = ""
    role_category: str = ""
    level: str = ""
    job_type: str = ""
    location: str = ""
    salary: JobSalary = Field(default_factory=JobSalary)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    education_requirement: str = ""
    experience_requirement: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    summary: str = ""


class JobSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    skill_name: str
    skill_type: Literal["required", "preferred", "optional"]
    importance: float
    confidence: float
    created_at: datetime


class JobAnalysisRead(BaseModel):
    job: JobRead
    structured_job: StructuredJob
    requirements: JobRequirements
    skills: list[JobSkillRead]


class JobImportRequest(BaseModel):
    mode: Literal["single", "mock"] = "single"
    raw_jd: str | None = Field(default=None, min_length=1)
    platform: str = Field(default="manual", min_length=1, max_length=100)
    external_job_id: str | None = Field(default=None, max_length=300)
    title: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    source_url: str | None = Field(default=None, max_length=2000)
    limit: int = Field(default=30, ge=1, le=100)
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source(self) -> JobImportRequest:
        if self.mode == "single" and not self.raw_jd:
            raise ValueError("raw_jd is required when mode is single")
        return self


class JobImportResponse(BaseModel):
    items: list[JobAnalysisRead]
    created: int
    duplicates: int
    total: int
