from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

KnowledgeIndexMode = Literal["incremental", "backfill"]
KnowledgeIndexStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
KnowledgeIndexItemStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "SKIPPED", "FAILED"]
KnowledgeHealthStatus = Literal["not_built", "partial", "needs_update", "ready"]


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


class KnowledgeRunProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    progress: int
    processed_jobs: int
    total_jobs: int
    error: str | None


class KnowledgeHealthRead(BaseModel):
    status: KnowledgeHealthStatus
    ready: bool
    jobs_total: int
    document_count: int
    indexed_jobs: int
    compatible_jobs: int
    needs_update_jobs: int
    chunk_count: int
    embedded_chunk_count: int
    coverage_percent: float
    embedding_model: str
    embedding_dimensions: int
    updated_at: datetime | None
    latest_run: KnowledgeRunProgressRead | None


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
