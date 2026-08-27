from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.models.entities import (
    AgentRun,
    Application,
    BrowserTask,
    Campaign,
    CampaignJob,
    RankingRun,
)
from app.models.states import ApplicationStatus, CampaignJobStatus, CampaignStatus
from app.repositories.campaigns import CampaignRepository
from app.repositories.matching import MatchingRepository
from app.schemas.campaigns import (
    ApplicationAction,
    CampaignApproveRequest,
    CampaignCreate,
    CampaignRejectRequest,
    CampaignUpdate,
    CuratedCampaignCreate,
)
from app.schemas.ranking import JobRankingRequest
from app.services.application_state import (
    ApplicationStateMachine,
    CampaignStateMachine,
    InvalidStateTransitionError,
)
from app.services.ranking_runs import RankingRunService, stop_ranking_run


class CampaignNotFoundError(ValueError):
    """Raised when a requested campaign does not exist."""


class CampaignResumeNotFoundError(ValueError):
    """Raised when a campaign has no usable resume."""


class CampaignCandidateError(ValueError):
    """Raised when candidate approval input is invalid."""


class CampaignMaintenanceError(ValueError):
    """Raised when a campaign cannot safely be edited or deleted."""


class ApplicationNotFoundError(ValueError):
    """Raised when a requested application does not exist."""


class CampaignService:
    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings or get_settings()
        self.repository = CampaignRepository(session)
        self.matching_repository = MatchingRepository(session)
        self.campaign_state = CampaignStateMachine()
        self.application_state = ApplicationStateMachine()

    async def list_campaigns(self) -> tuple[list[Campaign], int]:
        return await self.repository.list_campaigns()

    async def get_campaign(self, campaign_id: UUID) -> Campaign:
        campaign = await self.repository.get_campaign(campaign_id)
        if campaign is None:
            raise CampaignNotFoundError("Campaign not found")
        return campaign

    async def create(self, payload: CampaignCreate) -> Campaign:
        resume = (
            await self.matching_repository.get_resume(payload.resume_id)
            if payload.resume_id
            else await self.matching_repository.get_default_resume()
        )
        if resume is None:
            raise CampaignResumeNotFoundError(
                "Upload or select a resume before creating a campaign"
            )
        filters = dict(payload.filters)
        if payload.keywords:
            filters["keywords"] = list(dict.fromkeys(payload.keywords))
        campaign = Campaign(
            user_id=resume.user_id,
            resume_id=resume.id,
            name=payload.name,
            status=CampaignStatus.DRAFT.value,
            query=payload.query,
            min_score=payload.min_score,
            max_jobs=payload.max_jobs,
            scoring_mode=payload.scoring_mode,
            target_cities=payload.target_cities,
            filters=filters,
        )
        return await self.repository.commit_campaign(campaign)

    async def update(self, campaign_id: UUID, payload: CampaignUpdate) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        if campaign.status != CampaignStatus.DRAFT.value:
            raise CampaignMaintenanceError("Only draft campaigns can be edited")

        if "resume_id" in payload.model_fields_set:
            if payload.resume_id is None:
                raise CampaignResumeNotFoundError("A campaign must use a resume")
            resume = await self.matching_repository.get_resume(payload.resume_id)
            if resume is None:
                raise CampaignResumeNotFoundError("Resume not found")
            campaign.resume_id = resume.id

        for field in (
            "name",
            "query",
            "min_score",
            "max_jobs",
            "scoring_mode",
            "target_cities",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(campaign, field, value)

        filters = dict(payload.filters) if payload.filters is not None else dict(campaign.filters)
        if payload.keywords is not None:
            filters["keywords"] = list(
                dict.fromkeys(value.strip() for value in payload.keywords if value.strip())
            )
        campaign.filters = filters
        return await self.repository.commit_campaign(campaign)

    async def delete(self, campaign_id: UUID) -> None:
        campaign = await self.get_campaign(campaign_id)
        deletable = {
            CampaignStatus.DRAFT.value,
            CampaignStatus.COMPLETED.value,
            CampaignStatus.CANCELLED.value,
            CampaignStatus.FAILED.value,
        }
        if campaign.status not in deletable:
            raise CampaignMaintenanceError(
                "Active campaigns must be cancelled before deletion"
            )
        await self.session.execute(
            update(AgentRun)
            .where(AgentRun.campaign_id == campaign.id)
            .values(campaign_id=None)
        )
        await self.session.execute(
            update(BrowserTask)
            .where(BrowserTask.campaign_id == campaign.id)
            .values(campaign_id=None)
        )
        await self.session.delete(campaign)
        await self.session.commit()

    async def create_curated(self, payload: CuratedCampaignCreate) -> Campaign:
        """Create a campaign from an exact set explicitly selected by the user."""

        resume = (
            await self.matching_repository.get_resume(payload.resume_id)
            if payload.resume_id
            else await self.matching_repository.get_default_resume()
        )
        if resume is None:
            raise CampaignResumeNotFoundError(
                "Upload or select a resume before creating a campaign"
            )
        requested_ids = list(dict.fromkeys(payload.job_ids))
        jobs = await self.repository.get_jobs_by_ids(requested_ids)
        jobs_by_id = {job.id: job for job in jobs}
        missing = [job_id for job_id in requested_ids if job_id not in jobs_by_id]
        if missing:
            raise CampaignCandidateError("One or more selected jobs do not exist")

        campaign = Campaign(
            user_id=resume.user_id,
            resume_id=resume.id,
            name=payload.name,
            status=CampaignStatus.DRAFT.value,
            query=payload.query,
            min_score=0,
            max_jobs=len(requested_ids),
            scoring_mode="fast",
            target_cities=[],
            filters={
                "selection_mode": "user_curated",
                "job_ids": [str(job_id) for job_id in requested_ids],
            },
        )
        self.session.add(campaign)
        await self.session.flush()
        self.campaign_state.transition(campaign, CampaignStatus.RANKING)
        for rank, job_id in enumerate(requested_ids, start=1):
            job = jobs_by_id[job_id]
            campaign_job = CampaignJob(
                campaign_id=campaign.id,
                job_id=job.id,
                rank=rank,
                score=0,
                status=CampaignJobStatus.WAITING_APPROVAL.value,
            )
            application = Application(
                user_id=campaign.user_id,
                campaign_id=campaign.id,
                job_id=job.id,
                resume_id=resume.id,
                platform=job.platform,
                status=ApplicationStatus.DISCOVERED.value,
                message=payload.message,
                application_metadata={"selection_source": "user_curated"},
            )
            self.application_state.initialize(application)
            self.application_state.advance_to_waiting_approval(application)
            self.session.add_all([campaign_job, application])
        self.campaign_state.transition(campaign, CampaignStatus.WAITING_APPROVAL)
        return await self.repository.commit_campaign(campaign)

    async def start(self, campaign_id: UUID) -> tuple[Campaign, RankingRun | None]:
        campaign = await self.get_campaign(campaign_id)
        if campaign.resume_id is None:
            raise CampaignResumeNotFoundError("Campaign resume is no longer available")
        return await self._start_ranking(campaign)

    async def retry(self, campaign_id: UUID) -> tuple[Campaign, RankingRun | None]:
        campaign = await self.get_campaign(campaign_id)
        if campaign.status != CampaignStatus.FAILED.value:
            raise InvalidStateTransitionError(
                f"Campaign cannot retry ranking from {campaign.status}"
            )
        if campaign.resume_id is None:
            raise CampaignResumeNotFoundError("Campaign resume is no longer available")
        await self.session.execute(
            delete(Application).where(Application.campaign_id == campaign.id)
        )
        await self.session.execute(
            delete(CampaignJob).where(CampaignJob.campaign_id == campaign.id)
        )
        return await self._start_ranking(campaign)

    async def _start_ranking(
        self,
        campaign: Campaign,
    ) -> tuple[Campaign, RankingRun | None]:
        if campaign.resume_id is None:
            raise CampaignResumeNotFoundError("Campaign resume is no longer available")
        try:
            jobs = await self.repository.search_jobs(
                keywords=self._keywords(campaign),
                cities=campaign.target_cities,
                limit=self.settings.ranking_candidate_limit,
            )
            self.campaign_state.transition(campaign, CampaignStatus.RANKING)
            campaign.finished_at = None
            campaign = await self.repository.commit_campaign(campaign)
            if not jobs:
                self.campaign_state.transition(campaign, CampaignStatus.WAITING_APPROVAL)
                return await self.repository.commit_campaign(campaign), None

            run = await RankingRunService(self.session).create(
                JobRankingRequest(
                    resume_id=campaign.resume_id,
                    job_ids=[job.id for job in jobs],
                    candidate_limit=min(len(jobs), self.settings.ranking_candidate_limit),
                    top_k_embedding=max(self.settings.top_k_embedding, campaign.max_jobs),
                    top_k_rerank=max(self.settings.top_k_rerank, campaign.max_jobs),
                    top_k_llm=max(self.settings.top_k_llm, campaign.max_jobs),
                    final_top_k=campaign.max_jobs,
                    scoring_mode=campaign.scoring_mode,
                ),
                campaign_id=campaign.id,
                timeout_seconds=self.settings.ranking_timeout_seconds,
            )
            return await self.get_campaign(campaign.id), run
        except Exception:
            await self.session.rollback()
            campaign = await self.get_campaign(campaign.id)
            if campaign.status == CampaignStatus.RANKING.value:
                self.campaign_state.transition(campaign, CampaignStatus.FAILED)
                await self.repository.commit_campaign(campaign)
            raise

    async def approve(
        self,
        campaign_id: UUID,
        payload: CampaignApproveRequest,
    ) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        if campaign.status not in {
            CampaignStatus.WAITING_APPROVAL.value,
            CampaignStatus.RUNNING.value,
        }:
            raise InvalidStateTransitionError(
                f"Campaign cannot approve jobs from {campaign.status}"
            )
        candidates = {item.job_id: item for item in campaign.campaign_jobs}
        applications = {item.job_id: item for item in campaign.applications}
        requested = list(dict.fromkeys(payload.job_ids))
        missing = [job_id for job_id in requested if job_id not in candidates]
        if missing:
            raise CampaignCandidateError("One or more jobs do not belong to this campaign")
        for job_id in requested:
            campaign_job = candidates[job_id]
            application = applications.get(job_id)
            if application is None:
                raise CampaignCandidateError("Candidate application is missing")
            if campaign_job.status != CampaignJobStatus.WAITING_APPROVAL.value:
                raise CampaignCandidateError(f"Job {job_id} is not waiting for approval")
            self.application_state.transition(
                application,
                ApplicationStatus.APPROVED,
                event="user_approve",
            )
            campaign_job.status = CampaignJobStatus.APPROVED.value
            self.application_state.transition(
                application,
                ApplicationStatus.QUEUED,
                event="queue",
            )
            campaign_job.status = CampaignJobStatus.QUEUED.value
        if campaign.status == CampaignStatus.WAITING_APPROVAL.value:
            self.campaign_state.transition(campaign, CampaignStatus.RUNNING)
        return await self.repository.commit_campaign(campaign)

    async def reject(
        self,
        campaign_id: UUID,
        payload: CampaignRejectRequest,
    ) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        if campaign.status not in {
            CampaignStatus.WAITING_APPROVAL.value,
            CampaignStatus.RUNNING.value,
        }:
            raise InvalidStateTransitionError(
                f"Campaign cannot reject jobs from {campaign.status}"
            )
        candidates = {item.job_id: item for item in campaign.campaign_jobs}
        applications = {item.job_id: item for item in campaign.applications}
        requested = list(dict.fromkeys(payload.job_ids))
        missing = [job_id for job_id in requested if job_id not in candidates]
        if missing:
            raise CampaignCandidateError("One or more jobs do not belong to this campaign")
        for job_id in requested:
            campaign_job = candidates[job_id]
            application = applications.get(job_id)
            if application is None:
                raise CampaignCandidateError("Candidate application is missing")
            if campaign_job.status != CampaignJobStatus.WAITING_APPROVAL.value:
                raise CampaignCandidateError(f"Job {job_id} is not waiting for approval")
            self.application_state.cancel(application)
            application.failure_reason = "用户从投递计划中剔除"
            campaign_job.status = CampaignJobStatus.REJECTED.value
        return await self.repository.commit_campaign(campaign)

    async def pause(self, campaign_id: UUID) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        self.campaign_state.pause(campaign)
        jobs_by_id = {item.job_id: item for item in campaign.campaign_jobs}
        for application in campaign.applications:
            if application.status in {
                ApplicationStatus.QUEUED.value,
                ApplicationStatus.EXECUTING.value,
            }:
                self.application_state.pause(application)
                jobs_by_id[application.job_id].status = CampaignJobStatus.PAUSED.value
        return await self.repository.commit_campaign(campaign)

    async def resume(self, campaign_id: UUID) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        self.campaign_state.resume(campaign)
        jobs_by_id = {item.job_id: item for item in campaign.campaign_jobs}
        for application in campaign.applications:
            if application.status == ApplicationStatus.PAUSED.value:
                self.application_state.resume(application)
                jobs_by_id[application.job_id].status = application.status
        return await self.repository.commit_campaign(campaign)

    async def cancel(self, campaign_id: UUID) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        ranking_run = await RankingRunService(self.session).latest_for_campaign(campaign.id)
        if ranking_run is not None and ranking_run.status in {"PENDING", "RUNNING"}:
            await RankingRunService(self.session).cancel(ranking_run.id)
        self.campaign_state.cancel(campaign)
        jobs_by_id = {item.job_id: item for item in campaign.campaign_jobs}
        for application in campaign.applications:
            if application.status not in {
                ApplicationStatus.SUBMITTED.value,
                ApplicationStatus.CANCELLED.value,
            }:
                self.application_state.cancel(application)
                jobs_by_id[application.job_id].status = CampaignJobStatus.CANCELLED.value
        campaign = await self.repository.commit_campaign(campaign)
        if ranking_run is not None:
            stop_ranking_run(ranking_run.id)
        return campaign

    async def list_applications(self) -> tuple[list[Application], int]:
        return await self.repository.list_applications()

    async def transition_application(
        self,
        application_id: UUID,
        *,
        action: ApplicationAction,
        reason: str | None,
    ) -> Application:
        application = await self.repository.get_application(application_id)
        if application is None:
            raise ApplicationNotFoundError("Application not found")
        if action == "execute":
            self.application_state.transition(
                application, ApplicationStatus.EXECUTING, event="execute"
            )
        elif action == "submit":
            self.application_state.transition(
                application, ApplicationStatus.SUBMITTED, event="submit"
            )
        elif action == "pause":
            self.application_state.pause(application)
        elif action == "resume":
            self.application_state.resume(application)
        elif action == "retry":
            self.application_state.retry(application)
        elif action == "cancel":
            self.application_state.cancel(application)
        else:
            failure_status = {
                "captcha_required": ApplicationStatus.CAPTCHA_REQUIRED,
                "login_required": ApplicationStatus.LOGIN_REQUIRED,
                "platform_limit": ApplicationStatus.PLATFORM_LIMIT,
                "dom_changed": ApplicationStatus.DOM_CHANGED,
                "risk_control": ApplicationStatus.RISK_CONTROL,
                "unknown_state": ApplicationStatus.UNKNOWN_STATE,
                "fail": ApplicationStatus.FAILED,
            }[action]
            self.application_state.fail(
                application,
                failure_status,
                reason or failure_status.value,
            )
        campaign = await self.get_campaign(application.campaign_id)
        campaign_job = next(
            (item for item in campaign.campaign_jobs if item.job_id == application.job_id),
            None,
        )
        if campaign_job:
            campaign_job.status = self._campaign_job_status(application.status)
        await self.repository.commit_campaign(campaign)
        refreshed = await self.repository.get_application(application.id)
        if refreshed is None:
            raise ApplicationNotFoundError("Application disappeared during persistence")
        return refreshed

    @staticmethod
    def _keywords(campaign: Campaign) -> list[str]:
        configured = campaign.filters.get("keywords", [])
        keywords = [str(value) for value in configured] if isinstance(configured, list) else []
        if campaign.query:
            keywords.extend(re.findall(r"[\w+#.-]+", campaign.query))
        return list(dict.fromkeys(value for value in keywords if value))

    @staticmethod
    def _campaign_job_status(application_status: str) -> str:
        mapping = {
            ApplicationStatus.WAITING_APPROVAL.value: CampaignJobStatus.WAITING_APPROVAL.value,
            ApplicationStatus.APPROVED.value: CampaignJobStatus.APPROVED.value,
            ApplicationStatus.QUEUED.value: CampaignJobStatus.QUEUED.value,
            ApplicationStatus.EXECUTING.value: CampaignJobStatus.EXECUTING.value,
            ApplicationStatus.PAUSED.value: CampaignJobStatus.PAUSED.value,
            ApplicationStatus.SUBMITTED.value: CampaignJobStatus.SUBMITTED.value,
            ApplicationStatus.CANCELLED.value: CampaignJobStatus.CANCELLED.value,
        }
        return mapping.get(application_status, CampaignJobStatus.FAILED.value)
