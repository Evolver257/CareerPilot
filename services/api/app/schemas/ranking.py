from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.jobs import JobRead
from app.schemas.matching import JobScoreRead, Recommendation
from app.schemas.usage import LLMUsageRead

RankingStageName = Literal[
    "rule_filter",
    "embedding_rank",
    "reranker",
    "llm_judge",
    "deterministic_rank",
    "final_ranking",
]
RankingScoringMode = Literal["fast", "llm"]


class JobRankingRequest(BaseModel):
    resume_id: UUID | None = None
    job_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=500)
    search: str | None = Field(default=None, min_length=1, max_length=100)
    candidate_limit: int | None = Field(default=None, ge=1, le=500)
    top_k_embedding: int | None = Field(default=None, ge=1, le=500)
    top_k_rerank: int | None = Field(default=None, ge=1, le=500)
    top_k_llm: int | None = Field(default=None, ge=1, le=500)
    final_top_k: int | None = Field(default=None, ge=1, le=200)
    scoring_mode: RankingScoringMode = "llm"


class RankingConfigRead(BaseModel):
    candidate_limit: int
    top_k_embedding: int
    top_k_rerank: int
    top_k_llm: int
    final_top_k: int
    scoring_mode: RankingScoringMode = "llm"


class RankingTraceCandidate(BaseModel):
    job_id: UUID
    title: str
    rank: int | None = None
    score: float | None = None
    selected: bool
    passed: bool | None = None
    reasons: list[str] = Field(default_factory=list)
    sub_scores: dict[str, float] = Field(default_factory=dict)
    recommendation: Recommendation | None = None


class RankingTraceStage(BaseModel):
    name: RankingStageName
    input_count: int
    output_count: int
    duration_ms: float
    candidates: list[RankingTraceCandidate] = Field(default_factory=list)


class RankingTraceRead(BaseModel):
    run_id: UUID
    version: str
    started_at: datetime
    completed_at: datetime
    llm_calls: int
    cache_hits: int = 0
    fallback_count: int = 0
    token_usage: LLMUsageRead = Field(default_factory=LLMUsageRead)
    config: RankingConfigRead
    stages: list[RankingTraceStage]


class RankedJobRead(BaseModel):
    rank: int
    job: JobRead
    score: JobScoreRead


class JobRankingResponse(BaseModel):
    items: list[RankedJobRead]
    total_candidates: int
    trace: RankingTraceRead


RankingRunStatus = Literal[
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "TIMED_OUT",
]


class RankingRunRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    resume_id: UUID
    campaign_id: UUID | None = None
    timeout_seconds: int
    status: RankingRunStatus
    stage: str
    progress: int = Field(ge=0, le=100)
    processed_candidates: int
    total_candidates: int
    cache_hits: int
    llm_calls: int
    fallback_count: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
