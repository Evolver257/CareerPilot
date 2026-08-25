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
    "final_ranking",
]


class JobRankingRequest(BaseModel):
    resume_id: UUID | None = None
    job_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=500)
    search: str | None = Field(default=None, min_length=1, max_length=100)
    candidate_limit: int | None = Field(default=None, ge=1, le=500)
    top_k_embedding: int | None = Field(default=None, ge=1, le=500)
    top_k_rerank: int | None = Field(default=None, ge=1, le=500)
    top_k_llm: int | None = Field(default=None, ge=1, le=500)
    final_top_k: int | None = Field(default=None, ge=1, le=100)


class RankingConfigRead(BaseModel):
    candidate_limit: int
    top_k_embedding: int
    top_k_rerank: int
    top_k_llm: int
    final_top_k: int


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
