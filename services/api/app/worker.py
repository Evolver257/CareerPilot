"""PostgreSQL durable worker. No browser actions and no broker dual-write.

Session advisory locks use the SAME dedicated connection as business commits.
The commit fence rejects writes after ownership loss or persisted cancellation.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import event, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    AgentRun,
    EvaluationRun,
    KnowledgeIndexRun,
    KnowledgeIndexRunItem,
    RankingRun,
)
from app.models.work import BackgroundWork

logger = logging.getLogger("careerpilot.worker")
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"}
AGENT_TERMINAL = {"COMPLETED", "FAILED", "TIMED_OUT", "CANCELLED", "WAITING_FOR_USER"}


def model_for_kind(kind):
    return {
        "ranking": RankingRun,
        "knowledge": KnowledgeIndexRun,
        "agent": AgentRun,
        "evaluation": EvaluationRun,
    }[kind]


def is_business_terminal(kind, status):
    return status in (AGENT_TERMINAL if kind == "agent" else TERMINAL)


def work_status(kind, status):
    if kind == "agent" and status in {"COMPLETED", "WAITING_FOR_USER"}:
        return "SUCCEEDED"
    return status if status in TERMINAL else "FAILED"


def lock_key(kind, run_id):
    # Serialize knowledge writers across runs: two backfills may target the same job.
    identity = "knowledge-writer" if kind == "knowledge" else f"{kind}:{run_id}"
    return int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big") & ((1 << 63) - 1)


async def execute_business(session, work):
    from app.services.agent_runtime import AgentRuntime
    from app.services.knowledge_indexing import KnowledgeIndexService
    from app.services.llm_settings import LLMSettingsService
    from app.services.ranking_runs import RankingRunService

    if work.kind == "evaluation":
        from app.services.evaluations import EvaluationService

        return await EvaluationService(session).execute(work.run_id)

    settings = LLMSettingsService(session)
    embeddings = await settings.get_runtime_embedding_provider()
    if work.kind == "agent":
        provider = await settings.get_runtime_provider()
        return await AgentRuntime(
            session,
            provider,
            embedding_provider=embeddings,
        ).run_background(work.run_id)
    if work.kind == "ranking":
        return await RankingRunService(session).execute(
            work.run_id, await settings.get_runtime_provider(), embeddings
        )
    await session.execute(
        update(KnowledgeIndexRunItem)
        .where(
            KnowledgeIndexRunItem.run_id == work.run_id,
            KnowledgeIndexRunItem.status == "RUNNING",
        )
        .values(status="PENDING", started_at=None, error=None)
    )
    await session.commit()
    return await KnowledgeIndexService(session, embeddings).execute(work.run_id, embeddings)


async def run_once(engine, *, worker_id=None, handler=execute_business):
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Independent worker requires PostgreSQL advisory locks")
    worker_id = worker_id or f"worker-{os.getpid()}"
    async with AsyncSession(engine) as listing:
        ids = list(
            (
                await listing.scalars(
                    select(BackgroundWork.id)
                    .where(
                        BackgroundWork.status.in_(["PENDING", "RUNNING"]),
                        BackgroundWork.available_at <= datetime.now(UTC),
                    )
                    .order_by(BackgroundWork.updated_at, BackgroundWork.id)
                    .limit(64)
                )
            ).all()
        )
    for work_id in ids:
        async with engine.connect() as connection:
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                work = await session.get(BackgroundWork, work_id)
                if work is None or work.status not in {"PENDING", "RUNNING"}:
                    continue
                if work.kind not in {"ranking", "knowledge", "agent", "evaluation"}:
                    raise ValueError("Unsupported work kind")
                key = lock_key(work.kind, work.run_id)
                acquired = await session.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                )
                if not acquired:
                    await session.rollback()
                    continue
                fence = None
                monitor = None
                task = None
                try:
                    # Re-read after lock acquisition: another worker may have just completed it.
                    await session.refresh(work)
                    if work.status not in {"PENDING", "RUNNING"}:
                        continue
                    model = model_for_kind(work.kind)
                    run_id = work.run_id
                    generation = work.generation
                    run = await session.scalar(
                        select(model)
                        .where(model.id == run_id)
                        .execution_options(populate_existing=True)
                        .with_for_update()
                    )
                    if run is None or is_business_terminal(work.kind, run.status):
                        work.status = work_status(work.kind, run.status) if run else "CANCELLED"
                        await session.commit()
                        return True
                    if work.attempts >= 5:
                        work.status = run.status = "FAILED"
                        if work.kind in {"agent", "evaluation"}:
                            run.finished_at = datetime.now(UTC)
                        else:
                            run.stage = "failed"
                            run.completed_at = datetime.now(UTC)
                        if work.kind == "ranking" and run.campaign_id is not None:
                            from app.services.ranking_runs import RankingRunService

                            await RankingRunService(session)._fail_campaign(run.campaign_id)
                        work.error = run.error = (
                            "Worker interrupted repeatedly; explicit retry required"
                        )
                        await session.commit()
                        return True
                    work.status = "RUNNING"
                    work.worker_id = worker_id
                    work.attempts += 1
                    work.updated_at = datetime.now(UTC)
                    await session.commit()

                    def fence(sync_session, *args):
                        with sync_session.no_autoflush:
                            owned = sync_session.scalar(
                                text(
                                    "SELECT EXISTS (SELECT 1 FROM pg_locks "
                                    "WHERE locktype='advisory' AND pid=pg_backend_pid() "
                                    "AND classid=:hi AND objid=:lo AND objsubid=1 AND granted)"
                                ),
                                {"hi": key >> 32, "lo": key & 0xFFFFFFFF},
                            )
                            if not owned:
                                raise asyncio.CancelledError("Worker ownership lost")
                            # Read/lock cancellation BEFORE dirty ORM state is flushed.
                            state = sync_session.scalar(
                                select(model.status).where(model.id == run_id).with_for_update()
                            )
                            current_generation = sync_session.scalar(
                                select(BackgroundWork.generation)
                                .where(BackgroundWork.id == work_id)
                                .with_for_update()
                            )
                        if current_generation != generation:
                            raise asyncio.CancelledError("Task was superseded by retry")
                        if state == "CANCELLED":
                            raise asyncio.CancelledError("Task was cancelled")

                    event.listen(session.sync_session, "before_commit", fence)
                    event.listen(session.sync_session, "before_flush", fence)
                    task = asyncio.create_task(handler(session, work))

                    async def watch():
                        while not task.done():
                            await asyncio.sleep(0.5)
                            async with AsyncSession(engine) as observer:
                                state = await observer.scalar(
                                    select(model.status).where(model.id == run_id)
                                )
                                if state == "CANCELLED":
                                    task.cancel()
                                    return
                                await observer.execute(
                                    update(BackgroundWork)
                                    .where(
                                        BackgroundWork.id == work_id,
                                        BackgroundWork.status == "RUNNING",
                                    )
                                    .values(updated_at=datetime.now(UTC))
                                )
                                await observer.commit()

                    monitor = asyncio.create_task(watch())
                    result = await task
                    result_status = result.status
                    event.remove(session.sync_session, "before_commit", fence)
                    event.remove(session.sync_session, "before_flush", fence)
                    fence = None
                    await session.rollback()
                    work = await session.get(BackgroundWork, work_id, populate_existing=True)
                    final_status = work_status(work.kind, result_status)
                    await session.execute(
                        update(BackgroundWork)
                        .where(
                            BackgroundWork.id == work_id,
                            BackgroundWork.generation == generation,
                        )
                        .values(
                            status=final_status,
                            updated_at=datetime.now(UTC),
                            error=None
                            if final_status == "SUCCEEDED"
                            else "Business task did not succeed; inspect run",
                        )
                    )
                    await session.commit()
                    logger.info(
                        "work_finished id=%s status=%s attempts=%s",
                        work_id,
                        work.status,
                        work.attempts,
                    )
                except asyncio.CancelledError:
                    # Keep RUNNING for crash recovery unless cancellation was explicitly persisted.
                    if task and not task.done():
                        task.cancel()
                    raise
                except Exception:
                    logger.exception("work_interrupted id=%s", work_id)
                finally:
                    if monitor:
                        monitor.cancel()
                        await asyncio.gather(monitor, return_exceptions=True)
                    if task and not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    if fence:
                        event.remove(session.sync_session, "before_commit", fence)
                        event.remove(session.sync_session, "before_flush", fence)
                    await session.rollback()
                    # Never return a pooled connection with a session lock held.
                    try:
                        await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                        await session.commit()
                    except Exception:
                        await connection.invalidate()
                return True
    return False


async def main():
    from app.core.database import engine

    logger.info("worker_ready backend=postgresql advisory_lock=true")
    try:
        while True:
            try:
                busy = await run_once(engine)
            except asyncio.CancelledError:
                # A user cancellation is contained within the queue iteration;
                # process shutdown still propagates via the current task's cancellation count.
                if asyncio.current_task().cancelling():
                    raise
                busy = True
            except Exception:
                logger.exception("worker_poll_failed")
                busy = False
            await asyncio.sleep(0.2 if busy else 1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
