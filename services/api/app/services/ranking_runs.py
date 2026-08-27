from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.llm.provider import LLMProvider
from app.models.entities import Application, Campaign, CampaignJob, Job, JobScore, RankingRun
from app.models.states import ApplicationStatus, CampaignJobStatus, CampaignStatus
from app.repositories.matching import MatchingRepository
from app.schemas.ranking import JobRankingRequest, JobRankingResponse
from app.services.application_state import ApplicationStateMachine, CampaignStateMachine
from app.services.llm_settings import LLMSettingsService
from app.services.matching import MatchingResumeNotFoundError
from app.services.ranking import RankingService


class RankingRunNotFoundError(ValueError):
    """Raised when a persisted ranking run cannot be found."""


class RankingRunNotReadyError(ValueError):
    """Raised when a ranking result is requested before completion."""


class RankingRunCancelledError(RuntimeError):
    """Stops an active ranker after cancellation has been persisted."""


class RankingRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.application_state = ApplicationStateMachine()
        self.campaign_state = CampaignStateMachine()

    async def create(
        self,
        payload: JobRankingRequest,
        *,
        campaign_id: UUID | None = None,
        timeout_seconds: int | None = None,
    ) -> RankingRun:
        matching = MatchingRepository(self.session)
        resume = (
            await matching.get_resume(payload.resume_id)
            if payload.resume_id
            else await matching.get_default_resume()
        )
        if resume is None:
            raise MatchingResumeNotFoundError("Upload or select a resume before ranking")

        resolved_payload = payload.model_copy(update={"resume_id": resume.id})
        run = RankingRun(
            resume_id=resume.id,
            campaign_id=campaign_id,
            timeout_seconds=timeout_seconds or get_settings().ranking_timeout_seconds,
            status="PENDING",
            stage="queued",
            progress=0,
            request_payload=resolved_payload.model_dump(mode="json", exclude_none=True),
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get(self, run_id: UUID) -> RankingRun:
        run = await self.session.scalar(
            select(RankingRun)
            .execution_options(populate_existing=True)
            .where(RankingRun.id == run_id)
        )
        if run is None:
            raise RankingRunNotFoundError("Ranking run not found")
        return run

    async def latest_for_campaign(self, campaign_id: UUID) -> RankingRun | None:
        return await self.session.scalar(
            select(RankingRun)
            .where(RankingRun.campaign_id == campaign_id)
            .order_by(RankingRun.created_at.desc())
            .limit(1)
        )

    async def get_result(self, run_id: UUID) -> JobRankingResponse:
        run = await self.get(run_id)
        if run.status != "SUCCEEDED" or not run.result_payload:
            raise RankingRunNotReadyError("Ranking result is not ready")
        return JobRankingResponse.model_validate(run.result_payload)

    async def cancel(self, run_id: UUID) -> RankingRun:
        run = await self.get(run_id)
        if run.status in {"PENDING", "RUNNING"}:
            run.status = "CANCELLED"
            run.stage = "cancelled"
            run.error = "排名任务已由用户取消。"
            run.completed_at = datetime.now(UTC)
            await self.session.commit()
            await self.session.refresh(run)
        return run

    async def execute(
        self,
        run_id: UUID,
        provider: LLMProvider,
        embedding_provider: LLMProvider | None = None,
    ) -> RankingRun:
        run = await self.get(run_id)
        if run.status in {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}:
            return run

        now = datetime.now(UTC)
        run.status = "RUNNING"
        run.stage = "loading_candidates"
        run.progress = 1
        run.processed_candidates = 0
        run.total_candidates = 0
        run.cache_hits = 0
        run.llm_calls = 0
        run.fallback_count = 0
        run.error = None
        run.started_at = run.started_at or now
        run.completed_at = None
        await self.session.commit()

        elapsed = max(0.0, (now - run.started_at).total_seconds())
        remaining_timeout = max(0.0, run.timeout_seconds - elapsed)
        if remaining_timeout <= 0:
            return await self.fail(
                run_id,
                TimeoutError("排名任务超过允许执行时间"),
                status="TIMED_OUT",
            )

        async def update_progress(
            stage: str,
            progress: int,
            processed: int,
            total: int,
            cache_hits: int,
            llm_calls: int,
            fallback_count: int,
        ) -> None:
            current = await self.get(run_id)
            if current.status == "CANCELLED":
                raise RankingRunCancelledError("Ranking run was cancelled")
            current.stage = stage
            current.progress = progress
            current.processed_candidates = processed
            current.total_candidates = total
            current.cache_hits = cache_hits
            current.llm_calls = llm_calls
            current.fallback_count = fallback_count
            await self.session.commit()

        async def persist_candidate(
            job: Job,
            score: JobScore,
            processed: int,
            total: int,
        ) -> None:
            current = await self.get(run_id)
            if current.status == "CANCELLED":
                raise RankingRunCancelledError("Ranking run was cancelled")
            if current.campaign_id is not None:
                await self._persist_campaign_candidate(
                    current.campaign_id,
                    job,
                    score,
                    processed,
                    total,
                )

        try:
            payload = JobRankingRequest.model_validate(run.request_payload)
            async with asyncio.timeout(remaining_timeout):
                result = await RankingService(
                    self.session,
                    provider,
                    embedding_provider=embedding_provider,
                ).rank(
                    payload,
                    progress=update_progress,
                    candidate_completed=persist_candidate,
                )
        except RankingRunCancelledError:
            return await self.get(run_id)
        except TimeoutError as exc:
            return await self.fail(run_id, exc, status="TIMED_OUT")
        except Exception as exc:
            return await self.fail(run_id, exc)

        completed = await self.get(run_id)
        if completed.status == "CANCELLED":
            return completed
        completed.status = "SUCCEEDED"
        completed.stage = "completed"
        completed.progress = 100
        completed.processed_candidates = result.total_candidates
        completed.total_candidates = result.total_candidates
        completed.cache_hits = result.trace.cache_hits
        completed.llm_calls = result.trace.llm_calls
        completed.fallback_count = result.trace.fallback_count
        completed.result_payload = result.model_dump(mode="json")
        completed.completed_at = datetime.now(UTC)
        if completed.campaign_id is not None:
            await self._complete_campaign(completed.campaign_id, result)
        await self.session.commit()
        await self.session.refresh(completed)
        return completed

    async def fail(
        self,
        run_id: UUID,
        exc: Exception,
        *,
        status: str = "FAILED",
    ) -> RankingRun:
        await self.session.rollback()
        failed = await self.get(run_id)
        if failed.status == "CANCELLED":
            return failed
        failed.status = status
        failed.stage = "timed_out" if status == "TIMED_OUT" else "failed"
        failed.error = _public_error(exc)
        failed.completed_at = datetime.now(UTC)
        if failed.campaign_id is not None:
            await self._fail_campaign(failed.campaign_id)
        await self.session.commit()
        return failed

    async def _persist_campaign_candidate(
        self,
        campaign_id: UUID,
        job: Job,
        score: JobScore,
        processed: int,
        total: int,
    ) -> None:
        campaign = await self.session.get(Campaign, campaign_id)
        if campaign is None or campaign.status != CampaignStatus.RANKING.value:
            raise RankingRunCancelledError("Campaign is no longer ranking")
        if score.final_score < campaign.min_score:
            return

        campaign_job = await self.session.scalar(
            select(CampaignJob).where(
                CampaignJob.campaign_id == campaign_id,
                CampaignJob.job_id == job.id,
            )
        )
        if campaign_job is None:
            campaign_job = CampaignJob(
                campaign_id=campaign.id,
                job_id=job.id,
                rank=processed,
                score=score.final_score,
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
                application_metadata={"ranking_score_id": str(score.id)},
            )
            self.application_state.initialize(application)
            self.application_state.advance_to_waiting_approval(application)
            self.session.add_all([campaign_job, application])
        else:
            campaign_job.score = score.final_score

        ranked = list(
            (
                await self.session.scalars(
                    select(CampaignJob)
                    .where(CampaignJob.campaign_id == campaign_id)
                    .order_by(CampaignJob.score.desc(), CampaignJob.created_at)
                )
            ).all()
        )
        overflow = ranked[campaign.max_jobs :]
        for item in overflow:
            await self.session.execute(
                delete(Application).where(
                    Application.campaign_id == campaign_id,
                    Application.job_id == item.job_id,
                )
            )
            await self.session.delete(item)
        ranked = ranked[: campaign.max_jobs]
        for rank, item in enumerate(ranked, start=1):
            item.rank = rank
        await self.session.commit()

    async def _complete_campaign(
        self,
        campaign_id: UUID,
        result: JobRankingResponse,
    ) -> None:
        campaign = await self.session.get(Campaign, campaign_id)
        if campaign is None or campaign.status != CampaignStatus.RANKING.value:
            return
        selected = [item for item in result.items if item.score.final_score >= campaign.min_score]
        selected_ids = [item.job.id for item in selected]
        stale_condition = CampaignJob.campaign_id == campaign_id
        stale_app_condition = Application.campaign_id == campaign_id
        if selected_ids:
            stale_condition &= CampaignJob.job_id.not_in(selected_ids)
            stale_app_condition &= Application.job_id.not_in(selected_ids)
        await self.session.execute(delete(Application).where(stale_app_condition))
        await self.session.execute(delete(CampaignJob).where(stale_condition))

        for rank, item in enumerate(selected, start=1):
            campaign_job = await self.session.scalar(
                select(CampaignJob).where(
                    CampaignJob.campaign_id == campaign_id,
                    CampaignJob.job_id == item.job.id,
                )
            )
            if campaign_job is not None:
                campaign_job.rank = rank
                campaign_job.score = item.score.final_score
        self.campaign_state.transition(campaign, CampaignStatus.WAITING_APPROVAL)

    async def _fail_campaign(self, campaign_id: UUID) -> None:
        campaign = await self.session.get(Campaign, campaign_id)
        if campaign is not None and campaign.status == CampaignStatus.RANKING.value:
            self.campaign_state.transition(campaign, CampaignStatus.FAILED)


_active_ranking_tasks: dict[UUID, asyncio.Task[None]] = {}


async def execute_ranking_run(run_id: UUID) -> None:
    """Execute a persisted run using an independent database session."""

    async with SessionLocal() as session:
        service = RankingRunService(session)
        try:
            provider = await LLMSettingsService(session).get_runtime_provider()
            embedding_provider = await LLMSettingsService(
                session
            ).get_runtime_embedding_provider()
            await service.execute(run_id, provider, embedding_provider)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await service.fail(run_id, exc)


def schedule_ranking_run(run_id: UUID) -> None:
    existing = _active_ranking_tasks.get(run_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(execute_ranking_run(run_id))
    _active_ranking_tasks[run_id] = task
    task.add_done_callback(lambda _: _active_ranking_tasks.pop(run_id, None))


def stop_ranking_run(run_id: UUID) -> None:
    task = _active_ranking_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()


async def recover_interrupted_ranking_runs() -> list[UUID]:
    """Requeue durable runs after restart; completed score rows are reused as cache."""

    now = datetime.now(UTC)
    async with SessionLocal() as session:
        run_ids = list(
            (
                await session.scalars(
                    select(RankingRun.id).where(RankingRun.status.in_(["PENDING", "RUNNING"]))
                )
            ).all()
        )
        if run_ids:
            await session.execute(
                update(RankingRun)
                .where(RankingRun.id.in_(run_ids))
                .values(
                    status="PENDING",
                    stage="recovering",
                    error="API 服务重启，任务正在从已持久化进度恢复。",
                    updated_at=now,
                )
            )
            await session.commit()
        return run_ids


async def shutdown_ranking_tasks() -> None:
    tasks = [task for task in _active_ranking_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _public_error(exc: Exception) -> str:
    if isinstance(exc, MatchingResumeNotFoundError):
        return str(exc)
    if isinstance(exc, TimeoutError):
        return "排名任务执行超时；已完成评分已保存，可点击重试继续复用缓存。"
    return f"排名任务执行失败：{exc}"
