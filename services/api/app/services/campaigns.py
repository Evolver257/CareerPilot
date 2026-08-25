from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.models.entities import Application, Campaign, CampaignJob
from app.models.states import ApplicationStatus, CampaignJobStatus, CampaignStatus
from app.repositories.campaigns import CampaignRepository
from app.repositories.matching import MatchingRepository
from app.schemas.campaigns import (
    ApplicationAction,
    CampaignApproveRequest,
    CampaignCreate,
)
from app.schemas.ranking import JobRankingRequest
from app.services.application_state import (
    ApplicationStateMachine,
    CampaignStateMachine,
    InvalidStateTransitionError,
)
from app.services.ranking import RankingService


class CampaignNotFoundError(ValueError):
    """Raised when a requested campaign does not exist."""


class CampaignResumeNotFoundError(ValueError):
    """Raised when a campaign has no usable resume."""


class CampaignCandidateError(ValueError):
    """Raised when candidate approval input is invalid."""


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
            target_cities=payload.target_cities,
            filters=filters,
        )
        return await self.repository.commit_campaign(campaign)

    async def start(self, campaign_id: UUID) -> Campaign:
        campaign = await self.get_campaign(campaign_id)
        if campaign.resume_id is None:
            raise CampaignResumeNotFoundError("Campaign resume is no longer available")
        self.campaign_state.transition(campaign, CampaignStatus.RANKING)
        campaign = await self.repository.commit_campaign(campaign)
        try:
            jobs = await self.repository.search_jobs(
                keywords=self._keywords(campaign),
                cities=campaign.target_cities,
                limit=self.settings.ranking_candidate_limit,
            )
            if jobs:
                result = await RankingService(
                    self.session, self.provider, self.settings
                ).rank(
                    JobRankingRequest(
                        resume_id=campaign.resume_id,
                        job_ids=[job.id for job in jobs],
                        candidate_limit=min(len(jobs), self.settings.ranking_candidate_limit),
                        top_k_embedding=max(self.settings.top_k_embedding, campaign.max_jobs),
                        top_k_rerank=max(self.settings.top_k_rerank, campaign.max_jobs),
                        top_k_llm=max(self.settings.top_k_llm, campaign.max_jobs),
                        final_top_k=campaign.max_jobs,
                    )
                )
                jobs_by_id = {job.id: job for job in jobs}
                for item in result.items:
                    if item.score.final_score < campaign.min_score:
                        continue
                    job = jobs_by_id[item.job.id]
                    campaign_job = CampaignJob(
                        campaign_id=campaign.id,
                        job_id=job.id,
                        rank=item.rank,
                        score=item.score.final_score,
                        status=CampaignJobStatus.WAITING_APPROVAL.value,
                    )
                    application = Application(
                        user_id=campaign.user_id,
                        campaign_id=campaign.id,
                        job_id=job.id,
                        resume_id=campaign.resume_id,
                        platform=job.platform,
                        status=ApplicationStatus.DISCOVERED.value,
                        message="",
                        application_metadata={"ranking_score_id": str(item.score.id)},
                    )
                    self.application_state.initialize(application)
                    self.application_state.advance_to_waiting_approval(application)
                    self.session.add_all([campaign_job, application])
            self.campaign_state.transition(campaign, CampaignStatus.WAITING_APPROVAL)
            return await self.repository.commit_campaign(campaign)
        except Exception:
            await self.session.rollback()
            campaign = await self.get_campaign(campaign_id)
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
        self.campaign_state.cancel(campaign)
        jobs_by_id = {item.job_id: item for item in campaign.campaign_jobs}
        for application in campaign.applications:
            if application.status not in {
                ApplicationStatus.SUBMITTED.value,
                ApplicationStatus.CANCELLED.value,
            }:
                self.application_state.cancel(application)
                jobs_by_id[application.job_id].status = CampaignJobStatus.CANCELLED.value
        return await self.repository.commit_campaign(campaign)

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
