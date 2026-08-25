from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.matching import Recommendation


class ToolJob(BaseModel):
    id: UUID
    title: str
    location: str | None
    platform: str


class SearchJobsInput(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=30)
    cities: list[str] = Field(default_factory=list, max_length=30)
    limit: int = Field(default=100, ge=1, le=300)


class SearchJobsOutput(BaseModel):
    count: int
    job_ids: list[UUID]
    jobs: list[ToolJob]


class GetJobInput(BaseModel):
    job_id: UUID


class GetJobOutput(BaseModel):
    found: bool
    job: ToolJob | None = None
    description: str = ""


class AnalyzeJobsInput(BaseModel):
    job_ids: list[UUID] = Field(default_factory=list, max_length=300)


class AnalyzeJobsOutput(BaseModel):
    analyzed_count: int
    job_ids: list[UUID]


class RetrieveResumeInput(BaseModel):
    resume_id: UUID | None = None


class RetrieveResumeOutput(BaseModel):
    resume_id: UUID
    name: str
    skills: list[str]
    chunk_count: int


class ScoreJobToolInput(BaseModel):
    job_id: UUID
    resume_id: UUID | None = None


class ScoreJobToolOutput(BaseModel):
    job_id: UUID
    final_score: float
    recommendation: Recommendation
    reasoning_summary: str


class RankJobsToolInput(BaseModel):
    job_ids: list[UUID] = Field(default_factory=list, max_length=300)
    resume_id: UUID | None = None
    min_score: float = Field(default=0, ge=0, le=100)
    final_top_k: int = Field(default=10, ge=1, le=100)


class RankedToolJob(BaseModel):
    job_id: UUID
    title: str
    score: float
    recommendation: Recommendation
    score_id: UUID | None = None


class RankJobsToolOutput(BaseModel):
    count: int
    candidates: list[RankedToolJob]
    trace_run_id: UUID | None = None


class CreateCampaignToolInput(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    resume_id: UUID | None = None
    keywords: list[str] = Field(default_factory=list, max_length=30)
    cities: list[str] = Field(default_factory=list, max_length=30)
    min_score: float = Field(default=0, ge=0, le=100)
    max_jobs: int = Field(default=10, ge=1, le=100)


class CreateCampaignToolOutput(BaseModel):
    campaign_id: UUID
    status: str
    candidates: list[RankedToolJob]


class QueueApplicationInput(BaseModel):
    campaign_id: UUID
    job_ids: list[UUID] = Field(min_length=1, max_length=100)


class QueueApplicationOutput(BaseModel):
    campaign_id: UUID
    queued_count: int
    status: str


class RequestApprovalInput(BaseModel):
    campaign_id: UUID
    candidates: list[RankedToolJob]
    prompt: str


class RequestApprovalOutput(BaseModel):
    user_action_required: bool = True
    campaign_id: UUID
    candidate_count: int
    prompt: str
    candidates: list[RankedToolJob]


class ToolErrorOutput(BaseModel):
    error: str
    details: dict[str, Any] = Field(default_factory=dict)
