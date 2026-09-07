from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_evaluation_service
from app.models.entities import EvaluationDataset, EvaluationRun
from app.schemas.evaluations import (
    EvaluationCompareRead,
    EvaluationDatasetCreate,
    EvaluationDatasetRead,
    EvaluationRunCreate,
    EvaluationRunRead,
)
from app.services.evaluations import EvaluationError, EvaluationService

router = APIRouter(prefix="/api/evaluations", tags=["evaluations"])


def _dataset_read(item: EvaluationDataset) -> EvaluationDatasetRead:
    return EvaluationDatasetRead(
        id=item.id,
        name=item.name,
        suite=item.suite,
        version=item.version,
        label_status=item.label_status,
        sha256=item.sha256,
        case_count=item.case_count,
        created_at=item.created_at,
    )


def _run_read(item: EvaluationRun) -> EvaluationRunRead:
    return EvaluationRunRead(
        id=item.id,
        dataset_id=item.dataset_id,
        status=item.status,
        configuration=item.configuration,
        result=item.result,
        progress_current=item.progress_current,
        progress_total=item.progress_total,
        error=item.error,
        started_at=item.started_at,
        finished_at=item.finished_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _error(exc: EvaluationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/datasets", response_model=list[EvaluationDatasetRead])
async def list_datasets(
    service: EvaluationService = Depends(get_evaluation_service),
) -> list[EvaluationDatasetRead]:
    return [_dataset_read(item) for item in await service.list_datasets()]


@router.post(
    "/datasets", response_model=EvaluationDatasetRead, status_code=status.HTTP_201_CREATED
)
async def create_dataset(
    payload: EvaluationDatasetCreate,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationDatasetRead:
    try:
        return _dataset_read(await service.create_dataset(payload))
    except (EvaluationError, ValueError) as exc:
        raise _error(EvaluationError(str(exc))) from exc


@router.post("/datasets/import-tool-seed", response_model=EvaluationDatasetRead)
async def import_tool_seed(
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationDatasetRead:
    try:
        return _dataset_read(await service.import_tool_seed())
    except EvaluationError as exc:
        raise _error(exc) from exc


@router.get("/runs", response_model=list[EvaluationRunRead])
async def list_runs(
    service: EvaluationService = Depends(get_evaluation_service),
) -> list[EvaluationRunRead]:
    return [_run_read(item) for item in await service.list_runs()]


@router.post("/runs", response_model=EvaluationRunRead, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: EvaluationRunCreate,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunRead:
    try:
        return _run_read(await service.create_run(payload))
    except EvaluationError as exc:
        raise _error(exc) from exc


@router.get("/runs/{run_id}", response_model=EvaluationRunRead)
async def get_run(
    run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunRead:
    try:
        return _run_read(await service.get_run(run_id))
    except EvaluationError as exc:
        raise _error(exc) from exc


@router.post("/runs/{run_id}/cancel", response_model=EvaluationRunRead)
async def cancel_run(
    run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunRead:
    try:
        return _run_read(await service.cancel(run_id))
    except EvaluationError as exc:
        raise _error(exc) from exc


@router.post("/runs/{run_id}/retry", response_model=EvaluationRunRead)
async def retry_run(
    run_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationRunRead:
    try:
        return _run_read(await service.retry(run_id))
    except EvaluationError as exc:
        raise _error(exc) from exc


@router.get("/compare", response_model=EvaluationCompareRead)
async def compare_runs(
    left_id: UUID,
    right_id: UUID,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationCompareRead:
    try:
        left, right = await service.get_run(left_id), await service.get_run(right_id)
        left_summary = left.result.get("summary", {})
        right_summary = right.result.get("summary", {})
        common = set(left_summary) & set(right_summary)
        delta = {
            key: float(right_summary[key]) - float(left_summary[key])
            for key in common
            if isinstance(left_summary[key], int | float)
            and isinstance(right_summary[key], int | float)
        }
        return EvaluationCompareRead(
            left=_run_read(left), right=_run_read(right), metric_delta=delta
        )
    except EvaluationError as exc:
        raise _error(exc) from exc
