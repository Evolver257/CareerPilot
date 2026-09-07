from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EvaluationDatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    suite: Literal["tool_calling", "rag_retrieval", "answer"]
    version: str = Field(min_length=1, max_length=80)
    label_status: Literal["seed_requires_dual_review", "adjudicated_gold"]
    cases: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class EvaluationDatasetRead(BaseModel):
    id: UUID
    name: str
    suite: str
    version: str
    label_status: str
    sha256: str
    case_count: int
    created_at: datetime


class EvaluationRunCreate(BaseModel):
    dataset_id: UUID
    observations: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    configuration: dict[str, Any] = Field(default_factory=dict)
    require_gold: bool = False


class EvaluationRunRead(BaseModel):
    id: UUID
    dataset_id: UUID
    status: str
    configuration: dict[str, Any]
    result: dict[str, Any]
    progress_current: int
    progress_total: int
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EvaluationCompareRead(BaseModel):
    left: EvaluationRunRead
    right: EvaluationRunRead
    metric_delta: dict[str, float]

