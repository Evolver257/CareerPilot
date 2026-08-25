from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.states import (
    BrowserActionType,
    BrowserTaskEventType,
    BrowserTaskStatus,
)


class BrowserTarget(BaseModel):
    strategy: str = "semantic"
    name: str | None = None
    selector: str | None = None
    value: str | None = None


class BrowserAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    action: BrowserActionType
    target: BrowserTarget | None = None
    value: str | None = None
    url: str | None = None
    wait_ms: int = Field(default=0, ge=0, le=30_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrowserActionResult(BaseModel):
    type: str = "ACTION_RESULT"
    action_id: str
    success: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
    page_state: str | None = None
    error: str | None = None


class BrowserExtensionHello(BaseModel):
    type: str = "EXTENSION_HELLO"
    extension_version: str = "dev"
    tab_url: str | None = None


class BrowserTaskCreate(BaseModel):
    application_id: UUID
    platform: str = Field(default="mock", min_length=1, max_length=100)
    scenario: str = Field(default="SUCCESS", min_length=1, max_length=40)
    auto_start: bool = True


class BrowserTaskResumeRequest(BaseModel):
    decision: str = Field(default="resolved", min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class BrowserTaskEventRead(BaseModel):
    id: UUID
    task_id: UUID
    event_type: BrowserTaskEventType
    action_id: str | None
    sequence: int | None
    payload: dict[str, Any]
    created_at: datetime


class BrowserTaskRead(BaseModel):
    id: UUID
    user_id: UUID
    application_id: UUID
    campaign_id: UUID | None
    platform: str
    task_type: str
    scenario: str
    status: BrowserTaskStatus
    payload: dict[str, Any]
    result: dict[str, Any]
    current_action: dict[str, Any]
    failure_reason: str | None
    action_sequence: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[BrowserTaskEventRead]


class BrowserTaskListResponse(BaseModel):
    items: list[BrowserTaskRead]
    total: int


class BrowserTaskSocketMessage(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
