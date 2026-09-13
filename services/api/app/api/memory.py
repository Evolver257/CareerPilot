from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.dependencies import get_career_memory_service, get_memory_embedding_service
from app.models.entities import AgentMemory, AgentMemorySetting, MemoryCandidate
from app.schemas.memory import (
    MemoryBatchDelete,
    MemoryCandidateListResponse,
    MemoryCandidateRead,
    MemoryCreate,
    MemoryEmbeddingHealthRead,
    MemoryEmbeddingRunCreate,
    MemoryEmbeddingRunRead,
    MemoryExport,
    MemoryListResponse,
    MemoryMaintenanceResolve,
    MemoryRead,
    MemorySettingsRead,
    MemorySettingsUpdate,
    MemoryUpdate,
)
from app.services.career_memory import CareerMemoryService, MemoryError
from app.services.memory_embeddings import MemoryEmbeddingError, MemoryEmbeddingService

router = APIRouter(prefix="/api/career-memory", tags=["career-memory"])


def _embedding_run_read(item) -> MemoryEmbeddingRunRead:
    return MemoryEmbeddingRunRead(
        id=item.id,
        mode=item.mode,
        status=item.status,
        progress=item.progress,
        total=item.total,
        processed=item.processed,
        succeeded=item.succeeded,
        failed=item.failed,
        current_memory_id=item.current_memory_id,
        result_payload=item.result_payload or {},
        error=item.error,
        started_at=item.started_at,
        completed_at=item.completed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _settings_read(item: AgentMemorySetting) -> MemorySettingsRead:
    return MemorySettingsRead(
        enabled=item.enabled,
        auto_save_non_sensitive=item.auto_save_non_sensitive,
        retention_days=item.retention_days,
        allowed_types=item.allowed_types,
        allow_session_summaries=bool(getattr(item, "allow_session_summaries", False)),
        allow_unconfirmed_context=bool(getattr(item, "allow_unconfirmed_context", False)),
        memory_token_budget=int(getattr(item, "memory_token_budget", 700) or 700),
        extraction_confidence_threshold=float(
            getattr(item, "extraction_confidence_threshold", 0.75) or 0.75
        ),
    )


def _memory_read(item: AgentMemory) -> MemoryRead:
    return MemoryRead(
        id=item.id,
        memory_type=item.memory_type,
        memory_key=item.memory_key or item.memory_type.lower(),
        structured_value=item.structured_value or {},
        scope=item.scope,
        memory_class=item.memory_class or "SEMANTIC",
        stability=item.stability or "STABLE",
        importance=float(item.importance if item.importance is not None else 0.5),
        status=item.status or ("DELETED" if item.deleted_at else "ACTIVE"),
        content=item.content,
        source_quote=item.source_quote,
        extraction_method=item.extraction_method or "USER",
        extraction_version=item.extraction_version or "v1",
        supersedes_id=item.supersedes_id,
        last_verified_at=item.last_verified_at,
        pinned=bool(item.pinned),
        use_count=int(item.use_count or 0),
        confidence=item.confidence,
        user_confirmed=item.user_confirmed,
        sensitivity=item.sensitivity,
        provenance=item.provenance,
        valid_until=item.valid_until,
        last_used_at=item.last_used_at,
        deleted_at=item.deleted_at,
        deleted_from_status=item.deleted_from_status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _candidate_read(item: MemoryCandidate) -> MemoryCandidateRead:
    return MemoryCandidateRead(
        id=item.id,
        memory_type=item.memory_type,
        memory_key=item.memory_key or item.memory_type.lower(),
        structured_value=item.structured_value or {},
        scope=item.scope,
        memory_class=item.memory_class or "SEMANTIC",
        stability=item.stability or "STABLE",
        importance=float(item.importance if item.importance is not None else 0.5),
        content=item.content,
        source_quote=item.source_quote,
        extraction_method=item.extraction_method or "RULE",
        extraction_version=item.extraction_version or "v1",
        requires_confirmation=bool(getattr(item, "requires_confirmation", True)),
        conflict_type=item.conflict_type,
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
    status: str | None = Query(default=None),
    extraction_method: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryListResponse:
    items, total = await service.list(
        query=query,
        memory_type=memory_type,
        status=status,
        extraction_method=extraction_method,
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


@router.post("/items/{memory_id}/outdated", response_model=MemoryRead)
async def mark_memory_outdated(
    memory_id: UUID,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryRead:
    try:
        return _memory_read(await service.mark_outdated(memory_id))
    except MemoryError as exc:
        raise _error(exc) from exc


@router.get("/items/{memory_id}/history", response_model=list[MemoryRead])
async def memory_history(
    memory_id: UUID,
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> list[MemoryRead]:
    try:
        return [_memory_read(item) for item in await service.history(memory_id)]
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
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: CareerMemoryService = Depends(get_career_memory_service),
) -> MemoryCandidateListResponse:
    items, total = await service.list_candidates(limit=limit, offset=offset)
    return MemoryCandidateListResponse(
        items=[_candidate_read(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
        has_more=offset + len(items) < total,
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


@router.get("/embedding-runs", response_model=list[MemoryEmbeddingRunRead])
async def list_memory_embedding_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> list[MemoryEmbeddingRunRead]:
    runs = await service.list_runs(limit=limit, offset=offset)
    return [_embedding_run_read(item) for item in runs]


@router.get("/embedding-health", response_model=MemoryEmbeddingHealthRead)
async def memory_embedding_health(
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> MemoryEmbeddingHealthRead:
    health = await service.health()
    latest = health.get("latest_run")
    return MemoryEmbeddingHealthRead(
        **{key: value for key, value in health.items() if key != "latest_run"},
        latest_run=_embedding_run_read(latest) if latest is not None else None,
    )


@router.post(
    "/embedding-runs",
    response_model=MemoryEmbeddingRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_memory_embedding_run(
    payload: MemoryEmbeddingRunCreate,
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> MemoryEmbeddingRunRead:
    try:
        return _embedding_run_read(await service.create(mode=payload.mode))
    except MemoryEmbeddingError as exc:
        raise _error(MemoryError(str(exc))) from exc


@router.post(
    "/maintenance-runs",
    response_model=MemoryEmbeddingRunRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_memory_maintenance_run(
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> MemoryEmbeddingRunRead:
    try:
        return _embedding_run_read(await service.create_maintenance())
    except MemoryEmbeddingError as exc:
        raise _error(MemoryError(str(exc))) from exc


@router.post(
    "/maintenance-runs/{run_id}/resolve",
    response_model=MemoryEmbeddingRunRead,
)
async def resolve_memory_maintenance_action(
    run_id: UUID,
    payload: MemoryMaintenanceResolve,
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> MemoryEmbeddingRunRead:
    try:
        return _embedding_run_read(
            await service.resolve_maintenance_action(
                run_id,
                action=payload.action,
                source_memory_id=payload.source_memory_id,
                target_memory_id=payload.target_memory_id,
            )
        )
    except MemoryEmbeddingError as exc:
        raise _error(MemoryError(str(exc))) from exc


@router.get("/embedding-runs/{run_id}", response_model=MemoryEmbeddingRunRead)
async def get_memory_embedding_run(
    run_id: UUID,
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> MemoryEmbeddingRunRead:
    try:
        return _embedding_run_read(await service.get(run_id))
    except MemoryEmbeddingError as exc:
        raise _error(MemoryError(str(exc))) from exc


@router.post("/embedding-runs/{run_id}/cancel", response_model=MemoryEmbeddingRunRead)
async def cancel_memory_embedding_run(
    run_id: UUID,
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> MemoryEmbeddingRunRead:
    try:
        return _embedding_run_read(await service.cancel(run_id))
    except MemoryEmbeddingError as exc:
        raise _error(MemoryError(str(exc))) from exc


@router.post("/embedding-runs/{run_id}/retry", response_model=MemoryEmbeddingRunRead)
async def retry_memory_embedding_run(
    run_id: UUID,
    service: MemoryEmbeddingService = Depends(get_memory_embedding_service),
) -> MemoryEmbeddingRunRead:
    try:
        return _embedding_run_read(await service.retry(run_id))
    except MemoryEmbeddingError as exc:
        raise _error(MemoryError(str(exc))) from exc
