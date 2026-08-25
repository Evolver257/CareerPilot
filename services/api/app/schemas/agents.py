from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.states import AgentEventType, AgentRunStatus, AgentStepStatus


class AgentRunCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    resume_id: UUID | None = None
    auto_start: bool = True
    max_steps: int = Field(default=12, ge=1, le=50)
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)


class AgentRunResumeRequest(BaseModel):
    approved: bool | None = None
    selected_job_ids: list[UUID] = Field(default_factory=list, max_length=100)


class AgentStepRead(BaseModel):
    id: UUID
    run_id: UUID
    sequence: int
    step_type: str
    tool_name: str | None
    input: dict[str, Any]
    output: dict[str, Any]
    status: AgentStepStatus
    attempt: int
    latency_ms: float
    error: str | None
    created_at: datetime


class AgentEventRead(BaseModel):
    id: UUID
    run_id: UUID
    event_type: AgentEventType
    payload: dict[str, Any]
    created_at: datetime


class AgentRunRead(BaseModel):
    id: UUID
    user_id: UUID
    campaign_id: UUID | None
    agent_type: str
    status: AgentRunStatus
    input: dict[str, Any]
    output: dict[str, Any]
    state: dict[str, Any]
    memory: dict[str, Any]
    max_steps: int
    timeout_seconds: int
    max_retries: int
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[AgentStepRead]
    events: list[AgentEventRead]


class AgentRunListResponse(BaseModel):
    items: list[AgentRunRead]
    total: int


class AgentToolRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
