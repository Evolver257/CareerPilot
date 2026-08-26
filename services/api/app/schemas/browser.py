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


class BrowserTaskCampaignCreate(BaseModel):
    campaign_id: UUID
    platform: str | None = Field(default=None, min_length=1, max_length=100)
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


class BrowserTaskCampaignFailure(BaseModel):
    application_id: UUID
    reason: str


class BrowserTaskCampaignResponse(BaseModel):
    campaign_id: UUID
    queued_count: int
    created_count: int
    reused_count: int
    failed_count: int
    items: list[BrowserTaskRead]
    failures: list[BrowserTaskCampaignFailure]


class BrowserTaskCampaignItemRead(BaseModel):
    task: BrowserTaskRead
    job_id: UUID
    job_title: str
    application_status: str


class BrowserTaskCampaignGroupRead(BaseModel):
    campaign_id: UUID
    campaign_name: str
    campaign_status: str
    status: str
    platforms: list[str]
    task_count: int
    submitted_count: int
    active_count: int
    waiting_count: int
    failed_count: int
    cancelled_count: int
    created_at: datetime
    updated_at: datetime
    items: list[BrowserTaskCampaignItemRead]


class BrowserTaskCampaignGroupListResponse(BaseModel):
    items: list[BrowserTaskCampaignGroupRead]
    total: int


class PlatformAdapterRead(BaseModel):
    name: str
    label: str
    mode: str
    safe_for_automation: bool


class BrowserTaskSocketMessage(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
