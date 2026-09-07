from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_db,
    get_job_service,
    get_recruitment_provider_registry,
    get_recruitment_search_service,
)
from app.platforms.base import RecruitmentProviderError
from app.platforms.domain import JobSearchQuery
from app.platforms.registry import RecruitmentProviderRegistry
from app.schemas.boss import BossVisibleImportRequest, BossVisibleImportResponse
from app.schemas.jobs import JobRead
from app.schemas.recruitment import (
    RecruitmentImportResponse,
    RecruitmentPlatformRead,
    RecruitmentProviderHealthRead,
    RecruitmentSearchRequest,
    RecruitmentSearchResponse,
    VisibleRecruitmentImportRequest,
)
from app.services.boss import (
    BossVisibleImportError,
    import_visible_jobs,
)
from app.services.jobs import JobService
from app.services.recruitment_search import RecruitmentSearchService

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=list[RecruitmentPlatformRead])
async def list_recruitment_platforms(
    registry: RecruitmentProviderRegistry = Depends(get_recruitment_provider_registry),
) -> list[RecruitmentPlatformRead]:
    return [RecruitmentPlatformRead.model_validate(item) for item in registry.catalog()]


@router.get("/resolve")
async def resolve_recruitment_platform(
    url: str = Query(min_length=1, max_length=2000),
    registry: RecruitmentProviderRegistry = Depends(get_recruitment_provider_registry),
) -> dict[str, str | None]:
    provider = registry.resolve_by_url(url)
    return {"platform": provider.name if provider else None}


@router.post("/search", response_model=RecruitmentSearchResponse)
async def search_recruitment_platforms(
    payload: RecruitmentSearchRequest,
    service: RecruitmentSearchService = Depends(get_recruitment_search_service),
    session: AsyncSession = Depends(get_db),
) -> RecruitmentSearchResponse:
    if (
        payload.salary_min is not None
        and payload.salary_max is not None
        and payload.salary_min > payload.salary_max
    ):
        raise HTTPException(status_code=422, detail="salary_min cannot be greater than salary_max")
    result = await service.search(
        JobSearchQuery(
            keyword=payload.keyword,
            city=payload.city,
            district=payload.district,
            salary_min=payload.salary_min,
            salary_max=payload.salary_max,
            experience=tuple(payload.experience),
            education=tuple(payload.education),
            job_type=tuple(payload.job_type),
            industry=tuple(payload.industry),
            page=payload.page,
            page_size=payload.page_size,
            platforms=tuple(payload.platforms),
        )
    )
    ids = [job.id for job in result.jobs if job.id is not None]
    from app.repositories.campaigns import CampaignRepository

    stored = await CampaignRepository(session).get_jobs_by_ids(
        [item for item in ids if item is not None]
    )
    stored_by_id = {job.id: job for job in stored}
    return RecruitmentSearchResponse(
        items=[
            JobRead.model_validate(stored_by_id[job.id])
            for job in result.jobs
            if job.id in stored_by_id
        ],
        total=len(result.jobs),
        possible_duplicate_count=result.possible_duplicate_count,
        platform_status={
            key: RecruitmentProviderHealthRead.model_validate(value.__dict__)
            for key, value in result.platform_status.items()
        },
    )


@router.post(
    "/zhaopin/import-visible",
    response_model=RecruitmentImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_zhaopin_visible_jobs(
    payload: VisibleRecruitmentImportRequest,
    service: JobService = Depends(get_job_service),
    registry: RecruitmentProviderRegistry = Depends(get_recruitment_provider_registry),
) -> RecruitmentImportResponse:
    provider = registry.get("zhaopin")
    page_url = str(payload.page_url)
    if not provider.can_handle_url(page_url):
        raise HTTPException(status_code=422, detail="page_url must be a zhaopin.com URL")
    for item in payload.jobs:
        if not provider.can_handle_url(str(item.job_url)):
            raise HTTPException(status_code=422, detail="job_url must be a zhaopin.com URL")
    try:
        normalized_jobs = provider.parse_search_result(
            [item.model_dump(mode="json") for item in payload.jobs],
            page_url=page_url,
        )
    except RecruitmentProviderError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc

    collected_at = datetime.now(UTC)
    imported = []
    created = 0
    duplicates = 0
    updated = 0
    indexed_ids: list[UUID] = []
    for normalized in normalized_jobs:
        result = await service.import_normalized_job(normalized, auto_index=False)
        job = result.jobs[0]
        created += result.created
        duplicates += result.duplicates
        previous = job.raw_data or {}
        is_detail = normalized.raw_data.get("description_source") == "detail_page"
        was_detail = previous.get("description_source") == "detail_page"
        content_changed = normalized.description != previous.get("description", job.description)
        metadata_changed = any(
            previous.get(key) != value
            for key, value in (
                ("company_name", normalized.company_name),
                ("salary_text", normalized.salary_text),
                ("education", normalized.education),
                ("experience", normalized.experience),
            )
        )
        if not result.created and (
            (is_detail and (not was_detail or content_changed or metadata_changed))
            or (not was_detail and len(normalized.description) > len(job.description))
        ):
            context = [normalized.title]
            for label, value in (
                ("Company", normalized.company_name), ("Location", normalized.location),
                ("Salary", normalized.salary_text), ("Experience", normalized.experience),
                ("Education", normalized.education),
            ):
                if value:
                    context.append(f"{label}: {value}")
            context.append(normalized.description)
            job = await service.refresh_imported_job(
                job.id,
                raw_jd="\n".join(context),
                raw_data={
                    **dict(normalized.raw_data),
                    "company_name": normalized.company_name,
                    "salary_text": normalized.salary_text,
                    "education": normalized.education,
                    "experience": normalized.experience,
                    "platform_metadata": dict(normalized.platform_metadata),
                },
                title=normalized.title,
                location=normalized.location,
                source_url=normalized.source_url,
                auto_index=False,
                normalized_job=normalized,
            )
            updated += 1
            indexed_ids.append(job.id)
        elif result.created:
            indexed_ids.append(job.id)
        imported.append(
            await service.mark_collected(
                job.id,
                collected_at=collected_at,
                source_page=page_url,
            )
        )
    await service.enqueue_knowledge_index(indexed_ids)
    return RecruitmentImportResponse(
        platform="zhaopin",
        page_url=page_url,
        items=[JobRead.model_validate(job) for job in imported],
        created=created,
        duplicates=duplicates,
        updated=updated,
        total=len(imported),
    )


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
