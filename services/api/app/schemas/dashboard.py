from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.usage import LLMUsageRead


class DashboardSummary(BaseModel):
    jobs_total: int = Field(ge=0)
    high_match_jobs: int = Field(ge=0)
    campaigns_total: int = Field(ge=0)
    campaign_candidates: int = Field(ge=0)
    applications_total: int = Field(ge=0)
    submitted_applications: int = Field(ge=0)
    attention_required: int = Field(ge=0)


class FunnelStageRead(BaseModel):
    key: str
    label: str
    count: int = Field(ge=0)
    conversion_rate: float | None = Field(default=None, ge=0, le=100)


class ApplicationStatusCount(BaseModel):
    status: str
    count: int = Field(ge=0)


class AgentRuntimeStats(BaseModel):
    total_runs: int = Field(ge=0)
    active_runs: int = Field(ge=0)
    completed_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    failed_steps: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    average_latency_ms: float = Field(ge=0)


class DashboardRead(BaseModel):
    summary: DashboardSummary
    funnel: list[FunnelStageRead]
    application_status: list[ApplicationStatusCount]
    agent: AgentRuntimeStats
    token_usage: LLMUsageRead
    refreshed_at: datetime
