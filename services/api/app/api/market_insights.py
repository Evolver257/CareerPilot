from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import get_market_insight_service
from app.models.entities import MarketInsightReport
from app.schemas.market_insights import (
    MarketInsightCreate,
    MarketInsightListResponse,
    MarketInsightRead,
    MarketInsightResult,
)
from app.services.market_insights import (
    MarketInsightActionError,
    MarketInsightNotFoundError,
    MarketInsightService,
    schedule_market_insight,
    stop_market_insight,
)

router = APIRouter(prefix="/api/market-insights", tags=["market-insights"])


def _read(report: MarketInsightReport, *, cached: bool = False) -> MarketInsightRead:
    result = (
        MarketInsightResult.model_validate(report.report_payload)
        if report.report_payload
        else None
    )
    return MarketInsightRead(
        id=report.id,
        user_id=report.user_id,
        query=report.query,
        mode=report.mode,
        status=report.status,
        stage=report.stage,
        progress=report.progress,
        sample_count=report.sample_count,
        confidence=report.confidence,
        fingerprint=report.fingerprint,
        request=report.request_payload,
        report=result,
        source_job_ids=report.source_job_ids,
        llm_source=report.llm_source,
        error=report.error,
        created_at=report.created_at,
        updated_at=report.updated_at,
        started_at=report.started_at,
        completed_at=report.completed_at,
        cached=cached,
    )


@router.get("", response_model=MarketInsightListResponse)
async def list_market_insights(
    service: MarketInsightService = Depends(get_market_insight_service),
) -> MarketInsightListResponse:
    reports, total = await service.list()
    return MarketInsightListResponse(items=[_read(item) for item in reports], total=total)


@router.post("", response_model=MarketInsightRead, status_code=status.HTTP_202_ACCEPTED)
async def create_market_insight(
    payload: MarketInsightCreate,
    service: MarketInsightService = Depends(get_market_insight_service),
) -> MarketInsightRead:
    report, cached = await service.create(payload)
    if not cached:
        schedule_market_insight(report.id)
    return _read(report, cached=cached)


@router.get("/{report_id}", response_model=MarketInsightRead)
async def get_market_insight(
    report_id: UUID,
    service: MarketInsightService = Depends(get_market_insight_service),
) -> MarketInsightRead:
    try:
        return _read(await service.get(report_id))
    except MarketInsightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{report_id}/cancel", response_model=MarketInsightRead)
async def cancel_market_insight(
    report_id: UUID,
    service: MarketInsightService = Depends(get_market_insight_service),
) -> MarketInsightRead:
    try:
        report = await service.cancel(report_id)
        await stop_market_insight(report_id)
        return _read(report)
    except MarketInsightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{report_id}/retry", response_model=MarketInsightRead)
async def retry_market_insight(
    report_id: UUID,
    service: MarketInsightService = Depends(get_market_insight_service),
) -> MarketInsightRead:
    try:
        report = await service.retry(report_id)
        schedule_market_insight(report.id)
        return _read(report)
    except MarketInsightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketInsightActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_market_insight(
    report_id: UUID,
    service: MarketInsightService = Depends(get_market_insight_service),
) -> Response:
    try:
        await service.delete(report_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except MarketInsightNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketInsightActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
