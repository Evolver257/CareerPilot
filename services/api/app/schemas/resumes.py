from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ResumeEducation(BaseModel):
    institution: str = ""
    degree: str = ""
    field: str = ""
    start_date: str | None = None
    end_date: str | None = None
    details: list[str] = Field(default_factory=list)


class ResumeExperience(BaseModel):
    company: str = ""
    role: str = ""
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)


class ResumeProject(BaseModel):
    name: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class ResumeAward(BaseModel):
    name: str = ""
    issuer: str | None = None
    date: str | None = None
    details: str = ""


class ResumePublication(BaseModel):
    title: str = ""
    venue: str | None = None
    date: str | None = None
    details: str = ""


class ResumeProfile(BaseModel):
    education: list[ResumeEducation] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    experience: list[ResumeExperience] = Field(default_factory=list)
    awards: list[ResumeAward] = Field(default_factory=list)
    publications: list[ResumePublication] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    summary: str = ""


class ResumeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    original_filename: str | None
    raw_text: str
    structured_profile: ResumeProfile
    version: int
    is_default: bool
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class ResumeListResponse(BaseModel):
    items: list[ResumeRead]
    total: int


class ResumeChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resume_id: UUID
    chunk_type: str
    content: str
    metadata: dict[str, Any]
    embedding_dimensions: int
    created_at: datetime
