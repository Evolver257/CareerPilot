from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

MemoryType = Literal[
    "USER_PROFILE",
    "CAREER_GOAL",
    "JOB_PREFERENCE",
    "SKILL_BACKGROUND",
    "LEARNING_PROGRESS",
    "CONVERSATION_SUMMARY",
    "USER_CONFIRMED_FACT",
]


class MemorySettingsRead(BaseModel):
    enabled: bool
    auto_save_non_sensitive: bool
    retention_days: int
    allowed_types: list[MemoryType]


class MemorySettingsUpdate(BaseModel):
    enabled: bool | None = None
    auto_save_non_sensitive: bool | None = None
    retention_days: int | None = Field(default=None, ge=7, le=3650)
    allowed_types: list[MemoryType] | None = None


class MemoryCreate(BaseModel):
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=2000)


class MemoryUpdate(BaseModel):
    memory_type: MemoryType | None = None
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    user_confirmed: bool | None = None


class MemoryRead(BaseModel):
    id: UUID
    memory_type: MemoryType
    content: str
    confidence: float
    user_confirmed: bool
    sensitivity: str
    provenance: dict
    valid_until: datetime | None
    last_used_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    items: list[MemoryRead]
    total: int
    limit: int
    offset: int
    has_more: bool


class MemoryCandidateRead(BaseModel):
    id: UUID
    memory_type: MemoryType
    content: str
    confidence: float
    sensitivity: str
    status: str
    reason: str
    created_at: datetime


class MemoryCandidateListResponse(BaseModel):
    items: list[MemoryCandidateRead]
    total: int


class MemoryBatchDelete(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)


class MemoryExport(BaseModel):
    exported_at: datetime
    settings: MemorySettingsRead
    memories: list[MemoryRead]

