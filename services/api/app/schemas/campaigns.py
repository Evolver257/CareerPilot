from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.states import ApplicationStatus, CampaignJobStatus, CampaignStatus
from app.schemas.jobs import JobRead
from app.schemas.ranking import RankingRunRead, RankingScoringMode


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    resume_id: UUID | None = None
    query: str = Field(default="", max_length=500)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    min_score: float = Field(default=50.0, ge=0, le=100)
    max_jobs: int = Field(default=20, ge=1, le=100)
    scoring_mode: RankingScoringMode = "fast"
    target_cities: list[str] = Field(default_factory=list, max_length=30)
    filters: dict[str, Any] = Field(default_factory=dict)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    resume_id: UUID | None = None
    query: str | None = Field(default=None, max_length=500)
    keywords: list[str] | None = Field(default=None, max_length=30)
    min_score: float | None = Field(default=None, ge=0, le=100)
    max_jobs: int | None = Field(default=None, ge=1, le=100)
    scoring_mode: RankingScoringMode | None = None
    target_cities: list[str] | None = Field(default=None, max_length=30)
    filters: dict[str, Any] | None = None


class CuratedCampaignCreate(BaseModel):
    """Create an exact, user-selected candidate set without rerunning discovery."""

    name: str = Field(min_length=1, max_length=300)
    resume_id: UUID | None = None
    job_ids: list[UUID] = Field(min_length=1, max_length=20)
    query: str = Field(default="", max_length=500)
    message: str = Field(default="", max_length=2000)


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    resume_id: UUID | None
    name: str
    status: CampaignStatus
    query: str
    min_score: float
    max_jobs: int
    scoring_mode: RankingScoringMode
    target_cities: list[str]
    filters: dict[str, Any]
    candidate_count: int = 0
    waiting_approval_count: int = 0
    queued_count: int = 0
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    ranking_run: RankingRunRead | None = None


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    campaign_id: UUID
    job_id: UUID
    resume_id: UUID
    platform: str
    status: ApplicationStatus
    message: str
    applied_at: datetime | None
    failure_reason: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CampaignJobRead(BaseModel):
    id: UUID
    campaign_id: UUID
    job_id: UUID
    rank: int
    score: float
    status: CampaignJobStatus
    job: JobRead
    application: ApplicationRead | None
    created_at: datetime
    updated_at: datetime


class CampaignDetailRead(CampaignRead):
    candidate_jobs: list[CampaignJobRead]


class CampaignListResponse(BaseModel):
    items: list[CampaignRead]
    total: int


class CampaignApproveRequest(BaseModel):
    job_ids: list[UUID] = Field(min_length=1, max_length=100)


ApplicationAction = Literal[
    "execute",
    "submit",
    "pause",
    "resume",
    "retry",
    "cancel",
    "captcha_required",
    "login_required",
    "platform_limit",
    "dom_changed",
    "risk_control",
    "unknown_state",
    "fail",
]


class ApplicationTransitionRequest(BaseModel):
    action: ApplicationAction
    reason: str | None = Field(default=None, max_length=2000)


class ApplicationListItem(ApplicationRead):
    job: JobRead
    campaign_name: str


class ApplicationListResponse(BaseModel):
    items: list[ApplicationListItem]
    total: int
