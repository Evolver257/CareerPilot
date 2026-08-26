from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_job_service
from app.schemas.boss import BossVisibleImportRequest, BossVisibleImportResponse
from app.schemas.jobs import JobRead
from app.services.boss import (
    BossVisibleImportError,
    import_visible_jobs,
)
from app.services.jobs import JobService

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.post(
    "/boss/import-visible",
    response_model=BossVisibleImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_boss_visible_jobs(
    payload: BossVisibleImportRequest,
    service: JobService = Depends(get_job_service),
) -> BossVisibleImportResponse:
    try:
        jobs, created, duplicates, updated = await import_visible_jobs(payload, service)
    except BossVisibleImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return BossVisibleImportResponse(
        page_url=str(payload.page_url),
        items=[JobRead.model_validate(job) for job in jobs],
        created=created,
        duplicates=duplicates,
        updated=updated,
        total=len(jobs),
    )
