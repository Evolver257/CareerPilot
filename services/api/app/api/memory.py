from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.dependencies import get_career_memory_service
from app.models.entities import AgentMemory, AgentMemorySetting, MemoryCandidate
from app.schemas.memory import (
    MemoryBatchDelete,
    MemoryCandidateListResponse,
    MemoryCandidateRead,
    MemoryCreate,
    MemoryExport,
    MemoryListResponse,
    MemoryRead,
    MemorySettingsRead,
    MemorySettingsUpdate,
    MemoryUpdate,
)
from app.services.career_memory import CareerMemoryService, MemoryError

router = APIRouter(prefix="/api/career-memory", tags=["career-memory"])


def _settings_read(item: AgentMemorySetting) -> MemorySettingsRead:
    return MemorySettingsRead(
        enabled=item.enabled,
        auto_save_non_sensitive=item.auto_save_non_sensitive,
        retention_days=item.retention_days,
        allowed_types=item.allowed_types,
    )


def _memory_read(item: AgentMemory) -> MemoryRead:
    return MemoryRead(
        id=item.id,
        memory_type=item.memory_type,
        content=item.content,
        confidence=item.confidence,
        user_confirmed=item.user_confirmed,
        sensitivity=item.sensitivity,
        provenance=item.provenance,
        valid_until=item.valid_until,
        last_used_at=item.last_used_at,
        deleted_at=item.deleted_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _candidate_read(item: MemoryCandidate) -> MemoryCandidateRead:
    return MemoryCandidateRead(
        id=item.id,
        memory_type=item.memory_type,
        content=item.content,
        confidence=item.confidence,
        sensitivity=item.sensitivity,
        status=item.status,
        reason=item.reason,
        created_at=item.created_at,
    )


def _error(exc: MemoryError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/settings", response_model=MemorySettingsRead)
async def get_memory_settings(
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemorySettingsRead:
    return _settings_read(await service.get_settings())


@router.patch("/settings", response_model=MemorySettingsRead)
async def update_memory_settings(
    payload: MemorySettingsUpdate,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemorySettingsRead:
    return _settings_read(await service.update_settings(payload))


@router.get("/items", response_model=MemoryListResponse)
async def list_memories(
    query: str = Query(default="", max_length=200),
    memory_type: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryListResponse:
    items, total = await service.list(
        query=query,
        memory_type=memory_type,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return MemoryListResponse(
        items=[_memory_read(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
    )


@router.post("/items", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryRead:
    try:
        return _memory_read(await service.create(payload))
    except MemoryError as exc:
        raise _error(exc) from exc


@router.patch("/items/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: UUID,
    payload: MemoryUpdate,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryRead:
    try:
        return _memory_read(await service.update(memory_id, payload))
    except MemoryError as exc:
        raise _error(exc) from exc


@router.delete("/items/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    permanent: bool = Query(default=False),
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> Response:
    try:
        await service.delete(memory_id, permanent=permanent)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except MemoryError as exc:
        raise _error(exc) from exc


@router.post("/items/{memory_id}/restore", response_model=MemoryRead)
async def restore_memory(
    memory_id: UUID,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryRead:
    try:
        return _memory_read(await service.restore(memory_id))
    except MemoryError as exc:
        raise _error(exc) from exc


@router.post("/batch-delete")
async def batch_delete_memories(
    payload: MemoryBatchDelete,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> dict[str, int]:
    return {"deleted": await service.batch_delete(payload.ids)}


@router.delete("/items")
async def clear_memories(
    permanent: bool = Query(default=False),
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> dict[str, int]:
    return {"deleted": await service.clear(permanent=permanent)}


@router.get("/candidates", response_model=MemoryCandidateListResponse)
async def list_memory_candidates(
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryCandidateListResponse:
    items = await service.list_candidates()
    return MemoryCandidateListResponse(
        items=[_candidate_read(item) for item in items], total=len(items)
    )


@router.post("/candidates/{candidate_id}/accept", response_model=MemoryRead)
async def accept_memory_candidate(
    candidate_id: UUID,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryRead:
    try:
        item = await service.resolve_candidate(candidate_id, accept=True)
        assert item is not None
        return _memory_read(item)
    except MemoryError as exc:
        raise _error(exc) from exc


@router.post("/candidates/{candidate_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_memory_candidate(
    candidate_id: UUID,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> Response:
    try:
        await service.resolve_candidate(candidate_id, accept=False)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except MemoryError as exc:
        raise _error(exc) from exc


@router.get("/export", response_model=MemoryExport)
async def export_memories(
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryExport:
    settings = await service.get_settings()
    items, _ = await service.list(include_deleted=False, limit=10000)
    return MemoryExport(
        exported_at=datetime.now(UTC),
        settings=_settings_read(settings),
        memories=[_memory_read(item) for item in items],
    )
