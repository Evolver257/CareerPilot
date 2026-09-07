"""Versioned schemas shared by offline Agent and RAG evaluations.

Gold data must be independently reviewed.  Seed/silver cases are useful for
developing the harness, but the validators deliberately prevent them from
being reported as human gold.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

AnnotationStatus = Literal[
    "seed_requires_dual_review",
    "annotator_a",
    "annotator_b",
    "adjudicated_gold",
]


class ExpectedToolCall(BaseModel):
    tool_name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    required: bool = True
    forbidden: bool = False
    rationale: str = ""

    @model_validator(mode="after")
    def validate_role(self) -> ExpectedToolCall:
        if self.required and self.forbidden:
            raise ValueError("A tool call cannot be both required and forbidden")
        return self


class ToolEvaluationCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=200)
    dataset_version: str = Field(min_length=1, max_length=80)
    split: Literal["dev", "test"]
    category: str = Field(min_length=1, max_length=100)
    user_query: str = Field(min_length=1)
    conversation: list[dict[str, Any]] = Field(default_factory=list)
    expected_calls: list[ExpectedToolCall] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)
    annotation_status: AnnotationStatus = "seed_requires_dual_review"
    annotators: list[str] = Field(default_factory=list)
    adjudicated_by: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def validate_annotation(self) -> ToolEvaluationCase:
        if self.annotation_status == "adjudicated_gold":
            if len(set(self.annotators)) < 2 or not self.adjudicated_by:
                raise ValueError("Gold cases require two annotators and an adjudicator")
        return self


class ObservedToolCall(BaseModel):
    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal[
        "SUCCESS",
        "FAILED",
        "TIMEOUT",
        "RETRYING",
        "CANCELLED",
        "REJECTED",
    ] = "SUCCESS"
    schema_valid: bool | None = None
    semantically_valid: bool | None = None
    duplicate: bool = False
    unnecessary: bool = False
    retry_of: str | None = None
    latency_ms: float = Field(default=0, ge=0)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    cost: float = Field(default=0, ge=0)


class ToolTaskObservation(BaseModel):
    case_id: str
    calls: list[ObservedToolCall] = Field(default_factory=list)
    task_completed: bool = False
    final_answer: str = ""
    total_latency_ms: float = Field(default=0, ge=0)
    error: str | None = None


class RetrievalJudgment(BaseModel):
    document_id: str
    grade: int = Field(ge=0, le=3)
    evidence: str = ""
    hard_negative: bool = False


class RAGEvaluationCase(BaseModel):
    case_id: str
    dataset_version: str
    split: Literal["dev", "test"]
    topic: str
    query: str
    answerable: bool
    judgments: list[RetrievalJudgment] = Field(default_factory=list)
    reference_answer: str | None = None
    annotation_status: AnnotationStatus = "seed_requires_dual_review"
    annotators: list[str] = Field(default_factory=list)
    adjudicated_by: str | None = None

    @model_validator(mode="after")
    def validate_case(self) -> RAGEvaluationCase:
        relevant = [item for item in self.judgments if item.grade > 0]
        if self.answerable and not relevant:
            raise ValueError("Answerable RAG cases require at least one relevant judgment")
        if not self.answerable and relevant:
            raise ValueError("Unanswerable RAG cases cannot contain relevant judgments")
        if self.annotation_status == "adjudicated_gold":
            if len(set(self.annotators)) < 2 or not self.adjudicated_by:
                raise ValueError("Gold cases require two annotators and an adjudicator")
        return self


class AnswerEvaluationCase(BaseModel):
    case_id: str = Field(min_length=1, max_length=200)
    dataset_version: str = Field(min_length=1, max_length=80)
    split: Literal["dev", "test"]
    category: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1)
    answerable: bool = True
    expected_refusal: bool = False
    required_facts: list[str] = Field(default_factory=list)
    annotation_status: AnnotationStatus = "seed_requires_dual_review"
    annotators: list[str] = Field(default_factory=list)
    adjudicated_by: str | None = None

    @model_validator(mode="after")
    def validate_case(self) -> AnswerEvaluationCase:
        if self.expected_refusal == self.answerable:
            raise ValueError("expected_refusal must be the inverse of answerable")
        if self.annotation_status == "adjudicated_gold":
            if len(set(self.annotators)) < 2 or not self.adjudicated_by:
                raise ValueError("Gold cases require two annotators and an adjudicator")
        return self


class EvaluationRunManifest(BaseModel):
    run_id: str
    suite: str
    dataset_version: str
    dataset_sha256: str
    started_at: datetime
    finished_at: datetime
    git_commit: str | None = None
    git_dirty: bool | None = None
    seed: int
    configuration: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    label_status: str


def assert_gold_ready(
    cases: list[ToolEvaluationCase | RAGEvaluationCase | AnswerEvaluationCase],
) -> None:
    """Refuse to let silver/seed cases masquerade as a human gold result."""

    if not cases:
        raise ValueError("Empty evaluation set")
    pending = [item.case_id for item in cases if item.annotation_status != "adjudicated_gold"]
    if pending:
        preview = ", ".join(pending[:5])
        raise ValueError(f"Dataset is not adjudicated gold; pending cases: {preview}")
