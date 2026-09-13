from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.knowledge_search import JobKnowledgeFilters
from app.schemas.memory import MemoryType

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
    "collect_jobs_online",
    "search_job_knowledge",
    "retrieve_career_memory",
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


class CareerAdvisorSessionJobsBindRequest(BaseModel):
    message_id: UUID
    job_ids: list[UUID] = Field(min_length=1, max_length=200)
    source_type: Literal["automated_collection", "knowledge_base"] = "automated_collection"
    context: dict[str, Any] = Field(default_factory=dict)


class CareerAdvisorSessionJobsBindResponse(BaseModel):
    session_id: UUID
    linked_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    job_ids: list[UUID] = Field(default_factory=list)


class CareerAdvisorCollectionCompletedRequest(BaseModel):
    """Notify the advisor that an online collection has durable job results."""

    job_ids: list[UUID] = Field(min_length=1, max_length=200)
    collection_key: str | None = Field(default=None, max_length=200)


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
    # Memory routing is part of the planner contract. ``need_memory`` is kept
    # as a wire-compatible alias for clients that used the prompt spelling.
    needs_memory: bool = False
    need_memory: bool | None = None
    memory_reason: str = Field(default="", max_length=240)
    memory_types: list[MemoryType] = Field(default_factory=list, max_length=7)
    memory_keys: list[str] = Field(default_factory=list, max_length=12)
    memory_query: str = Field(default="", max_length=300)
    memory_limit: int = Field(default=6, ge=0, le=20)
    memory_token_budget: int = Field(default=700, ge=100, le=4000)


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
    platform: Literal["boss", "zhaopin", "auto"] | None = None
    city: str | None = Field(default=None, max_length=40)
    max_jobs: int | None = Field(default=None, ge=1, le=200)
    quick_score_threshold: float | None = Field(default=None, ge=0, le=100)
    decision_summary: str = Field(default="", max_length=200)


class CareerAdvisorOnlineSearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=160)
    rationale: str = Field(default="", max_length=240)
    evidence_sources: list[
        Literal[
            "user_request",
            "conversation",
            "resume_target_roles",
            "resume_skills",
            "resume_projects",
            "resume_experience",
        ]
    ] = Field(default_factory=list, max_length=6)
