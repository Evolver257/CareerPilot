from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.knowledge_search import JobKnowledgeFilters

CareerAdvisorIntent = Literal[
    "market_research",
    "learning_roadmap",
    "resume_gap",
    "role_comparison",
    "job_recommendation",
    "salary_analysis",
    "skill_analysis",
    "follow_up",
    "general_career_chat",
]

CareerAdvisorToolName = Literal[
    "search_jobs",
    "prepare_application",
    "search_job_knowledge",
    "aggregate_job_market",
    "explain_skill_demand",
    "build_learning_roadmap",
    "analyze_resume_gap",
    "compare_role_profiles",
    "recommend_jobs",
    "deep_dive_skill_requirements",
]


class CareerAdvisorSessionCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    resume_id: UUID | None = None
    context_filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)


class CareerAdvisorSessionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    resume_id: UUID | None = None
    context_filters: JobKnowledgeFilters | None = None


class CareerAdvisorMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    resume_id: UUID | None = None
    filters: JobKnowledgeFilters | None = None


class CareerAdvisorPrepareApplicationRequest(BaseModel):
    """Create a persisted, non-executing application confirmation draft."""

    message_id: UUID
    job_ids: list[UUID] = Field(min_length=1, max_length=200)
    resume_id: UUID | None = None
    plan_name: str | None = Field(default=None, max_length=300)
    message: str = Field(default="", max_length=2000)


class CareerAdvisorConfirmApplicationRequest(BaseModel):
    """Confirm one immutable draft before any external side effect starts."""

    message_id: UUID
    campaign_id: UUID
    confirmation_token: str = Field(min_length=20, max_length=2000)


class CareerAdvisorApplicationProgressRequest(BaseModel):
    message_id: UUID
    campaign_id: UUID


class CareerAdvisorCancelApplicationRequest(BaseModel):
    message_id: UUID
    campaign_id: UUID


class CareerAdvisorCitationRead(BaseModel):
    id: UUID
    message_id: UUID
    job_id: UUID | None
    chunk_id: UUID | None
    citation_index: int
    evidence: str
    metadata: dict[str, Any]
    created_at: datetime


class CareerAdvisorMessageRead(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    status: str
    intent: CareerAdvisorIntent | None
    model_provider: str | None
    model_name: str | None
    token_usage: dict[str, Any]
    tool_trace: list[dict[str, Any]]
    answer_metadata: dict[str, Any]
    latency_ms: float
    error_message: str | None
    ui_action: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    citations: list[CareerAdvisorCitationRead] = Field(default_factory=list)


class CareerAdvisorSessionRead(BaseModel):
    id: UUID
    user_id: UUID
    resume_id: UUID | None
    title: str
    agent_type: str
    context_filters: JobKnowledgeFilters
    summary: str
    created_at: datetime
    updated_at: datetime
    messages: list[CareerAdvisorMessageRead] = Field(default_factory=list)
    message_total: int = 0
    message_offset: int = 0
    message_has_more: bool = False


class CareerAdvisorSessionListResponse(BaseModel):
    items: list[CareerAdvisorSessionRead]
    total: int
    limit: int = 30
    offset: int = 0
    has_more: bool = False


class CareerAdvisorCitationListResponse(BaseModel):
    items: list[CareerAdvisorCitationRead]
    total: int


class CareerAdvisorStreamRequest(CareerAdvisorMessageCreate):
    pass


class CareerAdvisorRoleComparisonRequest(BaseModel):
    queries: list[str] = Field(min_length=2, max_length=2)
    filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)


class CareerAdvisorLLMOutput(BaseModel):
    advice_markdown: str = Field(default="", max_length=3000)
    next_actions: list[str] = Field(default_factory=list, max_length=6)


class CareerAdvisorToolPlan(BaseModel):
    normalized_question: str = Field(default="", max_length=500)
    expanded_questions: list[str] = Field(default_factory=list, max_length=3)
    intent: CareerAdvisorIntent
    rewritten_query: str = Field(min_length=1, max_length=300)
    needs_knowledge: bool = False
    tool_names: list[CareerAdvisorToolName] = Field(default_factory=list, max_length=3)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    decision_summary: str = Field(default="", max_length=200)
    # None keeps compatibility with older planner responses.  New planners
    # can explicitly stop after the selected tools instead of inheriting the
    # historical skill deep-dive behavior.
    deep_dive: bool | None = None


class CareerAdvisorObservationPlan(BaseModel):
    done: bool = True
    tool_names: list[CareerAdvisorToolName] = Field(default_factory=list, max_length=2)
    decision_summary: str = Field(default="", max_length=200)


class CareerAdvisorAgentDecision(BaseModel):
    action: Literal["answer", "tool"]
    tool_name: CareerAdvisorToolName | None = None
    query: str | None = Field(default=None, max_length=300)
    queries: list[str] = Field(default_factory=list, max_length=2)
    skills: list[str] = Field(default_factory=list, max_length=6)
    decision_summary: str = Field(default="", max_length=200)
