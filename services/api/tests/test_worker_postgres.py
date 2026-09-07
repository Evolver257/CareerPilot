"""Real PostgreSQL tests. Opt in with WORKER_TEST_DATABASE_URL (test DB only)."""

import asyncio
import os
import re
import sys
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.base import Base
from app.models.entities import Job, KnowledgeIndexRun, KnowledgeIndexRunItem
from app.models.work import BackgroundWork
from app.services.work_queue import enqueue_work
from app.worker import execute_business, lock_key, run_once

URL = os.getenv("WORKER_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL test database")


@pytest_asyncio.fixture
async def pg():
    if not URL.rsplit("/", 1)[-1].startswith(("careerpilot_eval", "test_")):
        raise RuntimeError("Refusing non-test database")
    schema = "test_worker_" + uuid4().hex
    admin = create_async_engine(URL)
    async with admin.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        URL, connect_args={"server_settings": {"search_path": f"{schema},public"}}
    )
    async with engine.begin() as conn:
        assert await conn.scalar(text("SELECT current_schema()")) == schema
        # checkfirst=True also finds identically named public tables through
        # search_path; force creation in our brand-new, isolated schema.
        await conn.run_sync(Base.metadata.create_all, checkfirst=False)
    yield engine, schema
    await engine.dispose()
    assert re.fullmatch(r"test_worker_[0-9a-f]{32}", schema)
    async with admin.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await admin.dispose()


async def queued(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        run = KnowledgeIndexRun(
            mode="backfill", status="PENDING", stage="queued", request_payload={}, result_payload={}
        )
        session.add(run)
        await session.flush()
        await enqueue_work(session, "knowledge", run.id)
        await enqueue_work(session, "knowledge", run.id)
        await session.commit()
        return run.id


async def test_atomic_rollback_and_duplicate_enqueue(pg):
    engine, _ = pg
    async with AsyncSession(engine) as session:
        await enqueue_work(session, "knowledge", uuid4())
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(BackgroundWork)) == 0
    await queued(engine)
    async with AsyncSession(engine) as session:
        assert await session.scalar(select(func.count()).select_from(BackgroundWork)) == 1


async def test_two_workers_and_completed_redelivery_have_one_effect(pg):
    engine, _ = pg
    run_id = await queued(engine)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def handler(session, work):
        calls.append(work.id)
        entered.set()
        await release.wait()
        run = await session.get(KnowledgeIndexRun, work.run_id)
        run.status = "SUCCEEDED"
        await session.commit()
        return run

    first = asyncio.create_task(run_once(engine, handler=handler))
    await asyncio.wait_for(entered.wait(), 10)
    assert await run_once(engine, handler=handler) is False
    release.set()
    await first
    async with AsyncSession(engine) as session:
        # Simulate acknowledgement loss after a committed business completion.
        await session.execute(update(BackgroundWork).values(status="RUNNING"))
        await session.commit()
    await run_once(engine, handler=handler)
    assert len(calls) == 1
    async with AsyncSession(engine) as session:
        assert (await session.get(KnowledgeIndexRun, run_id)).status == "SUCCEEDED"


async def test_cancel_during_inflight_work_cannot_be_overwritten(pg):
    engine, _ = pg
    run_id = await queued(engine)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(session, work):
        run = await session.get(KnowledgeIndexRun, work.run_id)
        entered.set()
        await release.wait()
        run.status = "SUCCEEDED"  # stale writer must be fenced before flush
        await session.commit()
        return run

    task = asyncio.create_task(run_once(engine, handler=handler))
    await asyncio.wait_for(entered.wait(), 10)
    async with AsyncSession(engine) as session:
        await session.execute(
            update(KnowledgeIndexRun)
            .where(KnowledgeIndexRun.id == run_id)
            .values(status="CANCELLED")
        )
        await session.commit()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await run_once(engine, handler=handler)
    async with AsyncSession(engine) as session:
        assert (await session.get(KnowledgeIndexRun, run_id)).status == "CANCELLED"
        assert await session.scalar(select(BackgroundWork.status)) == "CANCELLED"


async def test_killed_process_resumes_checkpoint_without_repeating_effect(pg):
    engine, schema = pg
    run_id = await queued(engine)
    env = {**os.environ, "WORKER_TEST_SCHEMA": schema, "WORKER_TEST_DATABASE_URL": URL}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-m",
        "evaluation.worker_crash_child",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        line = await asyncio.wait_for(process.stdout.readline(), 25)
        assert line.strip() == b"CHECKPOINT", (await process.stderr.read()).decode()
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()

    async def resume(session, work):
        run = await session.get(KnowledgeIndexRun, work.run_id)
        assert run.result_payload["first_step_committed"] is True
        run.result_payload = {**run.result_payload, "second_step_committed": True}
        run.status = "SUCCEEDED"
        await session.commit()
        return run

    assert await run_once(engine, handler=resume)
    async with AsyncSession(engine) as session:
        assert (await session.get(KnowledgeIndexRun, run_id)).result_payload["effects"] == 1
        assert await session.scalar(select(BackgroundWork.attempts)) == 2


async def test_actual_indexer_recovers_running_item_and_reuses_completed_result(pg, monkeypatch):
    from app.llm.provider import MockLLMProvider
    from app.schemas.knowledge import KnowledgeIndexRunCreate
    from app.services.knowledge_indexing import KnowledgeIndexService
    from app.services.llm_settings import LLMSettingsService

    async def provider(*args):
        return MockLLMProvider()

    monkeypatch.setattr(LLMSettingsService, "get_runtime_embedding_provider", provider)
    engine, _ = pg
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            Job(
                platform="test",
                title="RAG 实习",
                description="岗位职责\n开发知识库检索\n任职要求\n熟悉 Python 和 RAG",
                raw_data={},
                normalized_data={},
            )
        )
        await session.commit()
        run = await KnowledgeIndexService(session).create(
            KnowledgeIndexRunCreate(mode="backfill", auto_start=True)
        )
        run.status = "RUNNING"
        await session.execute(update(KnowledgeIndexRunItem).values(status="RUNNING"))
        await session.commit()
        run_id = run.id
    await run_once(engine, handler=execute_business)
    async with AsyncSession(engine) as session:
        run = await session.get(KnowledgeIndexRun, run_id)
        assert run.status == "SUCCEEDED", run.error
        assert run.succeeded_jobs == 1
        assert await session.scalar(select(BackgroundWork.status)) == "SUCCEEDED"


async def test_retry_generation_fences_old_writer_even_after_cancel_is_cleared(pg):
    engine, _ = pg
    run_id = await queued(engine)
    entered, release = asyncio.Event(), asyncio.Event()

    async def stale(session, work):
        run = await session.get(KnowledgeIndexRun, work.run_id)
        entered.set()
        await release.wait()
        run.status = "SUCCEEDED"
        await session.flush()  # explicit flush, not just commit, must also be fenced
        await session.commit()
        return run

    task = asyncio.create_task(run_once(engine, handler=stale))
    await asyncio.wait_for(entered.wait(), 10)
    async with AsyncSession(engine) as session:
        await session.execute(
            update(KnowledgeIndexRun)
            .where(KnowledgeIndexRun.id == run_id)
            .values(status="CANCELLED")
        )
        await session.commit()
        await session.execute(
            update(KnowledgeIndexRun).where(KnowledgeIndexRun.id == run_id).values(status="PENDING")
        )
        await enqueue_work(session, "knowledge", run_id, retry=True)
        await session.commit()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with AsyncSession(engine) as session:
        assert (await session.get(KnowledgeIndexRun, run_id)).status == "PENDING"
        work = await session.scalar(select(BackgroundWork))
        assert work.status == "PENDING"
        assert work.generation == 1
        assert work.attempts == 0


async def test_lost_advisory_lock_prevents_business_commit(pg):
    engine, _ = pg
    run_id = await queued(engine)

    async def lose_lock(session, work):
        key = lock_key(work.kind, work.run_id)
        await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        run = await session.get(KnowledgeIndexRun, work.run_id)
        run.status = "SUCCEEDED"
        await session.commit()
        return run

    with pytest.raises(asyncio.CancelledError):
        await run_once(engine, handler=lose_lock)
    async with AsyncSession(engine) as session:
        assert (await session.get(KnowledgeIndexRun, run_id)).status == "PENDING"


async def test_repeated_interruptions_are_bounded(pg):
    engine, _ = pg
    run_id = await queued(engine)
    async with AsyncSession(engine) as session:
        await session.execute(update(BackgroundWork).values(attempts=5, status="RUNNING"))
        await session.commit()

    async def forbidden(session, work):
        pytest.fail("Exhausted task must not run again")

    assert await run_once(engine, handler=forbidden)
    async with AsyncSession(engine) as session:
        assert (await session.get(KnowledgeIndexRun, run_id)).status == "FAILED"
        assert await session.scalar(select(BackgroundWork.status)) == "FAILED"


async def test_actual_ranker_resumes_using_persisted_scores(pg, monkeypatch):
    from app.llm.provider import MockLLMProvider
    from app.models.entities import JobScore, RankingRun
    from app.schemas.ranking import JobRankingRequest
    from app.services.llm_settings import LLMSettingsService
    from app.services.ranking_runs import RankingRunService
    from app.services.resumes import ResumeService

    async def provider(*args):
        return MockLLMProvider()

    monkeypatch.setattr(LLMSettingsService, "get_runtime_provider", provider)
    monkeypatch.setattr(LLMSettingsService, "get_runtime_embedding_provider", provider)
    engine, _ = pg
    async with AsyncSession(engine, expire_on_commit=False) as session:
        resume = await ResumeService(session, MockLLMProvider()).upload(
            filename="test.txt",
            content_type="text/plain",
            name="Test",
            user_id=None,
            data=b"Test User\nSkills\nPython, RAG, SQL\nEducation\nBachelor Computer Science",
        )
        job = Job(
            platform="test",
            title="Python Engineer",
            description="Python RAG SQL",
            raw_data={},
            normalized_data={},
        )
        session.add(job)
        await session.commit()
        run = await RankingRunService(session).create(
            JobRankingRequest(
                resume_id=resume.id, job_ids=[job.id], scoring_mode="fast", final_top_k=1
            )
        )
        run_id = run.id
    assert await run_once(engine)
    async with AsyncSession(engine) as session:
        run = await session.get(RankingRun, run_id)
        assert run.status == "SUCCEEDED", run.error
        score_ids = set((await session.scalars(select(JobScore.id))).all())
        assert len(score_ids) == 1
        # Recreate the state after score commit but before final run acknowledgement.
        run.status = "RUNNING"
        run.result_payload = {}
        await session.execute(
            update(BackgroundWork).where(BackgroundWork.kind == "ranking").values(status="RUNNING")
        )
        await session.commit()
    # First-time JD analysis may also enqueue knowledge indexing. Drain it too;
    # the worker intentionally does not promise priority for ranking over indexing.
    for _ in range(4):
        await run_once(engine)
        async with AsyncSession(engine) as session:
            if (await session.get(RankingRun, run_id)).status == "SUCCEEDED":
                break
    async with AsyncSession(engine) as session:
        run = await session.get(RankingRun, run_id)
        assert run.status == "SUCCEEDED", run.error
        assert run.cache_hits == 1
        assert run.llm_calls == 0
        assert set((await session.scalars(select(JobScore.id))).all()) == score_ids


async def test_exhausted_ranking_does_not_leave_campaign_stuck(pg):
    from app.models.entities import Campaign, RankingRun, Resume, User

    engine, _ = pg
    async with AsyncSession(engine, expire_on_commit=False) as session:
        user = User(email="test@example.test", name="Test")
        session.add(user)
        await session.flush()
        resume = Resume(user_id=user.id, name="Test")
        session.add(resume)
        await session.flush()
        campaign = Campaign(user_id=user.id, resume_id=resume.id, name="Test", status="RANKING")
        session.add(campaign)
        await session.flush()
        run = RankingRun(resume_id=resume.id, campaign_id=campaign.id, status="RUNNING")
        session.add(run)
        await session.flush()
        await enqueue_work(session, "ranking", run.id)
        await session.execute(update(BackgroundWork).values(attempts=5))
        await session.commit()
        run_id, campaign_id = run.id, campaign.id
    assert await run_once(engine)
    async with AsyncSession(engine) as session:
        run = await session.get(RankingRun, run_id)
        assert run.status == "FAILED"
        assert run.completed_at is not None
        assert (await session.get(Campaign, campaign_id)).status == "FAILED"
