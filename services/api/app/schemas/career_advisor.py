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


class CareerAdvisorSessionListResponse(BaseModel):
    items: list[CareerAdvisorSessionRead]
    total: int


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
