from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

KnowledgeIndexMode = Literal["incremental", "backfill"]
KnowledgeIndexStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
KnowledgeIndexItemStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "SKIPPED", "FAILED"]


class KnowledgeIndexRunCreate(BaseModel):
    mode: KnowledgeIndexMode = "incremental"
    job_ids: list[UUID] = Field(default_factory=list, max_length=10000)
    force: bool = False
    auto_start: bool = True


class KnowledgeIndexRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mode: str
    status: str
    stage: str
    progress: int
    total_jobs: int
    processed_jobs: int
    succeeded_jobs: int
    skipped_jobs: int
    failed_jobs: int
    current_job_id: UUID | None
    request: dict[str, Any]
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class KnowledgeIndexRunListResponse(BaseModel):
    items: list[KnowledgeIndexRunRead]
    total: int


class KnowledgeIndexRunItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    job_id: UUID
    status: str
    chunk_count: int
    reused_embedding_count: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class KnowledgeIndexRunItemListResponse(BaseModel):
    items: list[KnowledgeIndexRunItemRead]
    total: int
