from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
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
MemoryClass = Literal["SEMANTIC", "STATE", "EPISODIC"]
MemoryStability = Literal["STABLE", "TEMPORARY", "EVENT"]
MemoryStatus = Literal["ACTIVE", "SUPERSEDED", "EXPIRED", "DELETED"]
MemoryExtractionMethod = Literal["USER", "RULE", "LLM", "SUMMARY", "SYSTEM_DERIVED"]
MemoryConflictType = Literal["SAME", "EXTENDS", "UPDATES", "CONFLICTS", "UNRELATED"]


class MemorySettingsRead(BaseModel):
    enabled: bool
    auto_save_non_sensitive: bool
    retention_days: int
    allowed_types: list[MemoryType]
    allow_session_summaries: bool
    allow_unconfirmed_context: bool
    memory_token_budget: int
    extraction_confidence_threshold: float


class MemorySettingsUpdate(BaseModel):
    enabled: bool | None = None
    auto_save_non_sensitive: bool | None = None
    retention_days: int | None = Field(default=None, ge=7, le=3650)
    allowed_types: list[MemoryType] | None = None
    allow_session_summaries: bool | None = None
    allow_unconfirmed_context: bool | None = None
    memory_token_budget: int | None = Field(default=None, ge=200, le=4000)
    extraction_confidence_threshold: float | None = Field(default=None, ge=0.5, le=1.0)


class MemoryCreate(BaseModel):
    memory_type: MemoryType
    content: str = Field(min_length=1, max_length=2000)
    memory_key: str | None = Field(default=None, min_length=1, max_length=200)
    structured_value: dict[str, Any] = Field(default_factory=dict)
    scope: str | None = Field(default=None, max_length=120)
    memory_class: MemoryClass = "SEMANTIC"
    stability: MemoryStability = "STABLE"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source_quote: str | None = Field(default=None, max_length=2000)
    extraction_method: MemoryExtractionMethod = "USER"
    extraction_version: str = Field(default="v2", max_length=50)
    validity_days: int | None = Field(default=None, ge=1, le=3650)
    pinned: bool = False


class MemoryUpdate(BaseModel):
    memory_type: MemoryType | None = None
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    user_confirmed: bool | None = None
    memory_key: str | None = Field(default=None, min_length=1, max_length=200)
    structured_value: dict[str, Any] | None = None
    scope: str | None = Field(default=None, max_length=120)
    memory_class: MemoryClass | None = None
    stability: MemoryStability | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    pinned: bool | None = None
    valid_until: datetime | None = None


class MemoryRead(BaseModel):
    id: UUID
    memory_type: MemoryType
    memory_key: str
    structured_value: dict[str, Any]
    scope: str | None
    memory_class: MemoryClass
    stability: MemoryStability
    importance: float
    status: MemoryStatus
    content: str
    source_quote: str | None
    extraction_method: MemoryExtractionMethod
    extraction_version: str
    supersedes_id: UUID | None
    last_verified_at: datetime | None
    pinned: bool
    use_count: int
    confidence: float
    user_confirmed: bool
    sensitivity: str
    provenance: dict
    valid_until: datetime | None
    last_used_at: datetime | None
    deleted_at: datetime | None
    deleted_from_status: MemoryStatus | None
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
    memory_key: str
    structured_value: dict[str, Any]
    scope: str | None
    memory_class: MemoryClass
    stability: MemoryStability
    importance: float
    content: str
    source_quote: str | None
    extraction_method: MemoryExtractionMethod
    extraction_version: str
    requires_confirmation: bool
    conflict_type: str | None
    confidence: float
    sensitivity: str
    status: str
    reason: str
    created_at: datetime


class MemoryCandidateListResponse(BaseModel):
    items: list[MemoryCandidateRead]
    total: int
    limit: int = 20
    offset: int = 0
    has_more: bool = False


class MemoryEmbeddingRunCreate(BaseModel):
    mode: Literal["full", "incremental"] = "incremental"


class MemoryEmbeddingRunRead(BaseModel):
    id: UUID
    mode: str
    status: str
    progress: int
    total: int
    processed: int
    succeeded: int
    failed: int
    current_memory_id: UUID | None
    result_payload: dict[str, Any]
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryMaintenanceResolve(BaseModel):
    action: Literal["merge_duplicate", "supersede_conflict"]
    source_memory_id: UUID
    target_memory_id: UUID


class MemoryEmbeddingHealthRead(BaseModel):
    embedding_model: str
    embedding_dimensions: int
    provider_available: bool
    status: str
    total: int
    embedded: int
    pending: int
    failed: int
    latest_run: MemoryEmbeddingRunRead | None


class MemoryBatchDelete(BaseModel):
    ids: list[UUID] = Field(min_length=1, max_length=200)


class MemoryExport(BaseModel):
    exported_at: datetime
    settings: MemorySettingsRead
    memories: list[MemoryRead]


class MemoryExtractionCandidate(BaseModel):
    """Bounded, evidence-backed output accepted from an LLM extractor."""

    memory_type: MemoryType
    memory_class: MemoryClass = "SEMANTIC"
    memory_key: str = Field(min_length=1, max_length=200)
    normalized_content: str = Field(min_length=1, max_length=500)
    structured_value: dict[str, Any] = Field(default_factory=dict)
    scope: str | None = Field(default=None, max_length=120)
    stability: MemoryStability = "STABLE"
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_quote: str = Field(min_length=1, max_length=500)
    extraction_method: MemoryExtractionMethod = "LLM"
    extraction_version: str = Field(default="memory-v2-llm-1", max_length=50)
    requires_confirmation: bool = True
    validity_days: int | None = Field(default=None, ge=1, le=3650)


class MemoryExtractionResult(BaseModel):
    candidates: list[MemoryExtractionCandidate] = Field(default_factory=list, max_length=8)
