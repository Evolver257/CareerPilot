from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

QueryType = Literal[
    "literal",
    "paraphrase",
    "multi_constraint",
    "skill_requirements",
    "learning_path",
    "comparison",
    "no_answer",
    "hard_negative",
]
Answerability = Literal["answerable", "unanswerable", "uncertain"]


class RAGV2Query(BaseModel):
    query_id: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=1000)
    normalized_intent: str = Field(min_length=1, max_length=200)
    query_type: QueryType
    target_role: list[str] = Field(default_factory=list)
    target_skills: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    answerability: Answerability
    source: Literal["real_user", "human_written", "llm_assisted"]
    generator_model: str | None = None
    requires_human_review: bool = True
    template_group: str = Field(default="", max_length=120)
    source_query_id: str | None = None
    split: Literal["train", "dev", "test"] | None = None

    @field_validator("target_role", "target_skills")
    @classmethod
    def strip_terms(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]


class CorpusJob(BaseModel):
    dataset_version: str
    job_id: str
    platform: str
    external_job_id: str | None = None
    title: str
    company: str = ""
    description: str
    location: str = ""
    city: str = ""
    salary_min: int | float | None = None
    salary_max: int | float | None = None
    job_type: str = ""
    education_requirement: str = ""
    experience_requirement: str = ""
    education_level: str = "unknown"
    experience_level: str = "unknown"
    role_direction: str = "其他"
    source_url: str | None = None
    content_sha256: str
    jd_simhash: str
    dedup_keys: dict[str, str] = Field(default_factory=dict)
    normalized_fields: dict[str, Any] = Field(default_factory=dict)


class CandidateJob(BaseModel):
    query_id: str
    job_id: str
    candidate_rank: int = Field(ge=1)
    channels: list[str] = Field(default_factory=list)
    channel_ranks: dict[str, int] = Field(default_factory=dict)
    channel_scores: dict[str, float] = Field(default_factory=dict)


class EvidenceSpan(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str = Field(min_length=1)
    section: str | None = None

    @field_validator("end")
    @classmethod
    def end_after_start(cls, value: int, info) -> int:
        start = info.data.get("start", 0)
        if value <= start:
            raise ValueError("evidence span end must be greater than start")
        return value


class RAGAnnotation(BaseModel):
    annotation_id: str | None = None
    dataset_version: str
    query_id: str
    job_id: str
    annotator_id: str = Field(min_length=1, max_length=120)
    relevance_grade: Literal[-1, 0, 1, 2, 3]
    hard_constraint_violation: Literal["yes", "no", "uncertain"] = "uncertain"
    answerability_judgment: Answerability | None = None
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    annotation_note: str = Field(default="", max_length=4000)
    status: Literal["draft", "submitted", "skipped"] = "draft"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Adjudication(BaseModel):
    dataset_version: str
    query_id: str
    job_id: str
    annotator_a_id: str
    annotator_b_id: str
    annotator_a_label: int
    annotator_b_label: int
    adjudicated_label: Literal[-1, 0, 1, 2, 3]
    adjudicator_id: str = Field(min_length=1, max_length=120)
    decision_reason: str = Field(min_length=1, max_length=4000)
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def distinct_annotators(self) -> Adjudication:
        if self.annotator_a_id == self.annotator_b_id:
            raise ValueError("adjudication requires two different annotators")
        return self


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
