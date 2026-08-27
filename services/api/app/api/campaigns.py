from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_campaign_service
from app.models.entities import Application, Campaign
from app.models.states import CampaignJobStatus
from app.schemas.campaigns import (
    ApplicationListItem,
    ApplicationListResponse,
    ApplicationRead,
    ApplicationTransitionRequest,
    CampaignApproveRequest,
    CampaignCreate,
    CampaignDetailRead,
    CampaignJobRead,
    CampaignListResponse,
    CampaignRead,
    CampaignRejectRequest,
    CampaignUpdate,
    CuratedCampaignCreate,
)
from app.schemas.jobs import JobRead
from app.schemas.ranking import RankingRunRead
from app.services.application_state import InvalidStateTransitionError
from app.services.campaigns import (
    ApplicationNotFoundError,
    CampaignCandidateError,
    CampaignMaintenanceError,
    CampaignNotFoundError,
    CampaignResumeNotFoundError,
    CampaignService,
)
from app.services.ranking_runs import schedule_ranking_run

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
applications_router = APIRouter(prefix="/api/applications", tags=["applications"])


def _application_read(application: Application) -> ApplicationRead:
    return ApplicationRead(
        id=application.id,
        user_id=application.user_id,
        campaign_id=application.campaign_id,
        job_id=application.job_id,
        resume_id=application.resume_id,
        platform=application.platform,
        status=application.status,
        message=application.message,
        applied_at=application.applied_at,
        failure_reason=application.failure_reason,
        metadata=application.application_metadata,
        created_at=application.created_at,
        updated_at=application.updated_at,
    )


def _campaign_read(campaign: Campaign) -> CampaignRead:
    waiting = sum(
        item.status == CampaignJobStatus.WAITING_APPROVAL.value
        for item in campaign.campaign_jobs
    )
    queued = sum(
        item.status
        in {
            CampaignJobStatus.QUEUED.value,
            CampaignJobStatus.EXECUTING.value,
            CampaignJobStatus.PAUSED.value,
        }
        for item in campaign.campaign_jobs
    )
    ranking_run = max(campaign.ranking_runs, key=lambda item: item.created_at, default=None)
    return CampaignRead(
        id=campaign.id,
        user_id=campaign.user_id,
        resume_id=campaign.resume_id,
        name=campaign.name,
        status=campaign.status,
        query=campaign.query,
        min_score=campaign.min_score,
        max_jobs=campaign.max_jobs,
        scoring_mode=campaign.scoring_mode,
        target_cities=campaign.target_cities,
        filters=campaign.filters,
        candidate_count=len(campaign.campaign_jobs),
        waiting_approval_count=waiting,
        queued_count=queued,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        started_at=campaign.started_at,
        finished_at=campaign.finished_at,
        ranking_run=(RankingRunRead.model_validate(ranking_run) if ranking_run else None),
    )


def _campaign_detail(campaign: Campaign) -> CampaignDetailRead:
    applications = {item.job_id: item for item in campaign.applications}
    candidates = [
        CampaignJobRead(
            id=item.id,
            campaign_id=item.campaign_id,
            job_id=item.job_id,
            rank=item.rank,
            score=item.score,
            status=item.status,
            job=JobRead.model_validate(item.job),
            application=(
                _application_read(applications[item.job_id])
                if item.job_id in applications
                else None
            ),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in sorted(campaign.campaign_jobs, key=lambda value: value.rank)
    ]
    return CampaignDetailRead(**_campaign_read(campaign).model_dump(), candidate_jobs=candidates)


@router.get("", response_model=CampaignListResponse)
async def list_campaigns(
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignListResponse:
    campaigns, total = await service.list_campaigns()
    return CampaignListResponse(items=[_campaign_read(item) for item in campaigns], total=total)


@router.post("", response_model=CampaignDetailRead, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        return _campaign_detail(await service.create(payload))
    except CampaignResumeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/curated",
    response_model=CampaignDetailRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_curated_campaign(
    payload: CuratedCampaignCreate,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        return _campaign_detail(await service.create_curated(payload))
    except (CampaignResumeNotFoundError, CampaignCandidateError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{campaign_id}", response_model=CampaignDetailRead)
async def get_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        return _campaign_detail(await service.get_campaign(campaign_id))
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{campaign_id}", response_model=CampaignDetailRead)
async def update_campaign(
    campaign_id: UUID,
    payload: CampaignUpdate,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        return _campaign_detail(await service.update(campaign_id, payload))
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CampaignMaintenanceError, CampaignResumeNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
) -> None:
    try:
        await service.delete(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CampaignMaintenanceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


async def _campaign_action(campaign_id: UUID, action, service: CampaignService):
    try:
        return _campaign_detail(await action(campaign_id))
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CampaignResumeNotFoundError, InvalidStateTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{campaign_id}/start", response_model=CampaignDetailRead)
async def start_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        campaign, ranking_run = await service.start(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CampaignResumeNotFoundError, InvalidStateTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if ranking_run is not None:
        schedule_ranking_run(ranking_run.id)
    return _campaign_detail(campaign)


@router.post("/{campaign_id}/retry", response_model=CampaignDetailRead)
async def retry_campaign_ranking(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        campaign, ranking_run = await service.retry(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CampaignResumeNotFoundError, InvalidStateTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if ranking_run is not None:
        schedule_ranking_run(ranking_run.id)
    return _campaign_detail(campaign)


@router.post("/{campaign_id}/approve", response_model=CampaignDetailRead)
async def approve_campaign_jobs(
    campaign_id: UUID,
    payload: CampaignApproveRequest,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        return _campaign_detail(await service.approve(campaign_id, payload))
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CampaignCandidateError, InvalidStateTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{campaign_id}/reject", response_model=CampaignDetailRead)
async def reject_campaign_jobs(
    campaign_id: UUID,
    payload: CampaignRejectRequest,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    try:
        return _campaign_detail(await service.reject(campaign_id, payload))
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CampaignCandidateError, InvalidStateTransitionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{campaign_id}/pause", response_model=CampaignDetailRead)
async def pause_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    return await _campaign_action(campaign_id, service.pause, service)


@router.post("/{campaign_id}/resume", response_model=CampaignDetailRead)
async def resume_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    return await _campaign_action(campaign_id, service.resume, service)


@router.post("/{campaign_id}/cancel", response_model=CampaignDetailRead)
async def cancel_campaign(
    campaign_id: UUID,
    service: CampaignService = Depends(get_campaign_service),
) -> CampaignDetailRead:
    return await _campaign_action(campaign_id, service.cancel, service)


@applications_router.get("", response_model=ApplicationListResponse)
async def list_applications(
    service: CampaignService = Depends(get_campaign_service),
) -> ApplicationListResponse:
    applications, total = await service.list_applications()
    return ApplicationListResponse(
        items=[
            ApplicationListItem(
                **_application_read(item).model_dump(),
                job=JobRead.model_validate(item.job),
                campaign_name=item.campaign.name,
            )
            for item in applications
        ],
        total=total,
    )


@applications_router.post("/{application_id}/transition", response_model=ApplicationRead)
async def transition_application(
    application_id: UUID,
    payload: ApplicationTransitionRequest,
    service: CampaignService = Depends(get_campaign_service),
) -> ApplicationRead:
    try:
        application = await service.transition_application(
            application_id,
            action=payload.action,
            reason=payload.reason,
        )
    except ApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _application_read(application)
