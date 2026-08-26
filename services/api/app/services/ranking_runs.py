from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.llm.provider import LLMProvider
from app.models.entities import RankingRun
from app.repositories.matching import MatchingRepository
from app.schemas.ranking import JobRankingRequest, JobRankingResponse
from app.services.llm_settings import LLMSettingsService
from app.services.matching import MatchingResumeNotFoundError
from app.services.ranking import RankingService


class RankingRunNotFoundError(ValueError):
    """Raised when a persisted ranking run cannot be found."""


class RankingRunNotReadyError(ValueError):
    """Raised when a ranking result is requested before completion."""


class RankingRunService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: JobRankingRequest) -> RankingRun:
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
        run = await self.session.scalar(select(RankingRun).where(RankingRun.id == run_id))
        if run is None:
            raise RankingRunNotFoundError("Ranking run not found")
        return run

    async def get_result(self, run_id: UUID) -> JobRankingResponse:
        run = await self.get(run_id)
        if run.status != "SUCCEEDED" or not run.result_payload:
            raise RankingRunNotReadyError("Ranking result is not ready")
        return JobRankingResponse.model_validate(run.result_payload)

    async def execute(
        self,
        run_id: UUID,
        provider: LLMProvider,
    ) -> RankingRun:
        run = await self.get(run_id)
        if run.status == "SUCCEEDED":
            return run

        run.status = "RUNNING"
        run.stage = "loading_candidates"
        run.progress = max(run.progress, 1)
        run.error = None
        run.started_at = datetime.now(UTC)
        run.completed_at = None
        await self.session.commit()

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
            current.stage = stage
            current.progress = progress
            current.processed_candidates = processed
            current.total_candidates = total
            current.cache_hits = cache_hits
            current.llm_calls = llm_calls
            current.fallback_count = fallback_count
            await self.session.commit()

        try:
            payload = JobRankingRequest.model_validate(run.request_payload)
            result = await RankingService(self.session, provider).rank(
                payload,
                progress=update_progress,
            )
        except Exception as exc:
            return await self.fail(run_id, exc)

        completed = await self.get(run_id)
        completed.status = "SUCCEEDED"
        completed.stage = "completed"
        completed.progress = 100
        completed.total_candidates = result.total_candidates
        completed.cache_hits = result.trace.cache_hits
        completed.llm_calls = result.trace.llm_calls
        completed.fallback_count = result.trace.fallback_count
        completed.result_payload = result.model_dump(mode="json")
        completed.completed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(completed)
        return completed

    async def fail(self, run_id: UUID, exc: Exception) -> RankingRun:
        await self.session.rollback()
        failed = await self.get(run_id)
        failed.status = "FAILED"
        failed.stage = "failed"
        failed.error = _public_error(exc)
        failed.completed_at = datetime.now(UTC)
        await self.session.commit()
        return failed


async def execute_ranking_run(run_id: UUID) -> None:
    """Run after the short create request using an independent DB session."""

    async with SessionLocal() as session:
        service = RankingRunService(session)
        try:
            provider = await LLMSettingsService(session).get_runtime_provider()
            await service.execute(run_id, provider)
        except Exception as exc:
            await service.fail(run_id, exc)


async def fail_interrupted_ranking_runs() -> None:
    """Prevent persisted runs from remaining stuck after an API restart."""

    now = datetime.now(UTC)
    async with SessionLocal() as session:
        await session.execute(
            update(RankingRun)
            .where(RankingRun.status.in_(["PENDING", "RUNNING"]))
            .values(
                status="FAILED",
                stage="interrupted",
                error="API 服务重启导致任务中断，请重新开始排名；已完成评分缓存仍会复用。",
                completed_at=now,
                updated_at=now,
            )
        )
        await session.commit()


def _public_error(exc: Exception) -> str:
    if isinstance(exc, MatchingResumeNotFoundError):
        return str(exc)
    return f"排名任务执行失败：{exc}"
