from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Recommendation = Literal["strong_apply", "apply", "maybe", "skip"]


class JobScoreRequest(BaseModel):
    resume_id: UUID | None = None
    force: bool = False


class QuickScoreBatchRequest(BaseModel):
    job_ids: list[UUID] = Field(min_length=1, max_length=200)
    resume_id: UUID | None = None


class QuickScoreRead(BaseModel):
    job_id: UUID
    resume_id: UUID
    score: float = Field(ge=0, le=100)
    rules_passed: bool
    rule_reasons: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    recommendation: Recommendation
    reasoning_summary: str = ""
    direction_score: float = Field(default=0, ge=0, le=100)
    score_confidence: float = Field(default=0, ge=0, le=1)
    score_status: Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT_DATA", "FAILED"] = "SUFFICIENT"
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    hard_constraint_ledger: list[dict[str, Any]] = Field(default_factory=list)
    hard_constraint_passed: bool = True
    component_scores: dict[str, float] = Field(default_factory=dict)
    requirement_matches: list[dict[str, Any]] = Field(default_factory=list)
    cached: bool = False


class QuickScoreBatchResponse(BaseModel):
    items: list[QuickScoreRead]


class ResumeEvidenceRead(BaseModel):
    chunk_id: UUID
    chunk_type: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    semantic_score: float = Field(ge=0, le=100)
    rerank_score: float = Field(ge=0, le=100)


class LLMJudgeOutput(BaseModel):
    score: float = Field(default=0, ge=0, le=100)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommendation: Recommendation = "skip"
    reasoning_summary: str = ""


class JobScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_id: UUID
    resume_id: UUID
    semantic_score: float
    skill_score: float
    education_score: float
    experience_score: float
    location_score: float
    preference_score: float
    llm_score: float
    final_score: float
    rules_passed: bool
    rule_reasons: list[str]
    matched_skills: list[str]
    missing_skills: list[str]
    strengths: list[str]
    gaps: list[str]
    risks: list[str]
    resume_evidence: list[ResumeEvidenceRead]
    recommendation: Recommendation
    reasoning_summary: str
    score_version: str
    input_fingerprint: str | None = None
    judge_source: str = "llm"
    weights: dict[str, float]
    direction_score: float = 0
    score_confidence: float = 0
    score_status: str = "SUFFICIENT"
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    hard_constraint_ledger: list[dict[str, Any]] = Field(default_factory=list)
    hard_constraint_passed: bool = True
    created_at: datetime
