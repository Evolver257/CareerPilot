from __future__ import annotations

from hashlib import sha256

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm.provider import MockLLMProvider
from app.models.base import Base
from app.models.entities import (
    Job,
    JobKnowledgeChunk,
    JobKnowledgeDocument,
    JobSkill,
    JobSkillFact,
    JobVersion,
    KnowledgeIndexRunItem,
    SkillTaxonomy,
)
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.services import knowledge_indexing
from app.services.job_knowledge import (
    build_job_knowledge_chunks,
    canonicalize_skill,
)
from app.services.knowledge_indexing import KnowledgeIndexService


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as database_session:
        yield database_session
    await engine.dispose()


def _job(description: str, *, title: str = "AI Agent 实习生") -> Job:
    return Job(
        platform="test",
        external_job_id=None,
        title=title,
        description=description,
        location="北京",
        salary_min=200,
        salary_max=300,
        job_type="实习",
        education_requirement="本科及以上",
        experience_requirement="经验不限",
        raw_data={"company_name": "CareerPilot Labs", "salary_text": "200-300元/天"},
        normalized_data={
            "structured_job": {
                "title": title,
                "role_category": "AI Agent",
                "level": "实习",
                "job_type": "实习",
                "location": "北京",
                "education_requirement": "本科及以上",
                "experience_requirement": "经验不限",
                "required_skills": ["Python", "RAG"],
                "preferred_skills": ["Torch"],
                "responsibilities": ["负责构建 RAG 服务", "参与 Agent 应用开发"],
                "benefits": ["导师指导"],
                "keywords": ["大模型", "检索增强生成"],
                "summary": "参与大模型应用开发",
            },
            "requirements": {
                "education": "本科及以上",
                "experience": "经验不限",
                "responsibilities": ["负责构建 RAG 服务", "参与 Agent 应用开发"],
                "qualifications": ["熟悉 Python 和 RAG"],
                "preferred_qualifications": ["了解 Torch"],
                "benefits": ["导师指导"],
            },
        },
        content_hash=sha256(description.encode("utf-8")).hexdigest(),
    )


@pytest.mark.asyncio
async def test_chunker_uses_semantic_sections_and_skill_aliases(session: AsyncSession) -> None:
    job = _job("岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python，了解 Torch")
    job.skills.append(JobSkill(skill_name="Torch", skill_type="required", confidence=0.9))
    drafts = build_job_knowledge_chunks(job)

    assert {draft.section_type for draft in drafts} >= {
        "overview",
        "responsibilities",
        "required_skills",
        "preferred_skills",
        "education",
        "experience",
    }
    assert any("## 岗位职责" in draft.content for draft in drafts)
    assert canonicalize_skill("Torch") == "PyTorch"


@pytest.mark.asyncio
async def test_backfill_is_incremental_and_reuses_embeddings(session: AsyncSession) -> None:
    job = _job("岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python")
    job.skills.extend(
        [
            JobSkill(skill_name="Python", skill_type="required", confidence=0.95),
            JobSkill(skill_name="RAG", skill_type="required", confidence=0.9),
            JobSkill(skill_name="Torch", skill_type="preferred", confidence=0.7),
        ]
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    provider = MockLLMProvider()
    service = KnowledgeIndexService(session, provider)
    run = await service.create(
        KnowledgeIndexRunCreate(mode="backfill", auto_start=False)
    )
    completed = await service.execute(run.id, provider)

    assert completed.status == "SUCCEEDED"
    assert completed.progress == 100
    assert completed.total_jobs == 1
    assert completed.succeeded_jobs == 1

    document = await session.scalar(
        select(JobKnowledgeDocument).where(JobKnowledgeDocument.job_id == job.id)
    )
    assert document is not None
    chunks = list(
        (
            await session.scalars(
                select(JobKnowledgeChunk).where(JobKnowledgeChunk.job_id == job.id)
            )
        ).all()
    )
    assert len(chunks) >= 6
    assert all(len(chunk.embedding or []) == 384 for chunk in chunks)

    facts = list(
        (
            await session.scalars(
                select(JobSkillFact).where(JobSkillFact.job_id == job.id)
            )
        ).all()
    )
    assert {fact.requirement_type for fact in facts} == {"required", "preferred"}
    taxonomy_names = set(
        (
            await session.scalars(
                select(SkillTaxonomy.canonical_name).join(
                    JobSkillFact, JobSkillFact.skill_id == SkillTaxonomy.id
                )
            )
        ).all()
    )
    assert {"Python", "RAG", "PyTorch"} <= taxonomy_names

    second_run = await service.create(
        KnowledgeIndexRunCreate(mode="incremental", auto_start=False)
    )
    assert second_run.total_jobs == 0
    assert second_run.status == "SUCCEEDED"

    job.description += "\n新增 Docker 部署要求"
    job.content_hash = sha256(job.description.encode("utf-8")).hexdigest()
    await session.commit()
    changed_run = await service.create(
        KnowledgeIndexRunCreate(mode="incremental", auto_start=False)
    )
    assert changed_run.total_jobs == 1
    changed_completed = await service.execute(changed_run.id, provider)
    assert changed_completed.status == "SUCCEEDED"
    versions = list(
        (
            await session.scalars(select(JobVersion).where(JobVersion.job_id == job.id))
        ).all()
    )
    assert len(versions) == 2
    assert sum(version.is_current for version in versions) == 1


@pytest.mark.asyncio
async def test_failed_index_can_be_retried_from_persisted_item(session: AsyncSession) -> None:
    job = _job("岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    service = KnowledgeIndexService(session, MockLLMProvider())
    run = await service.create(
        KnowledgeIndexRunCreate(mode="backfill", auto_start=False)
    )
    failed = await service.execute(run.id, MockLLMProvider(dimensions=3))
    assert failed.status == "FAILED"
    assert failed.failed_jobs == 1
    item = await session.scalar(
        select(KnowledgeIndexRunItem).where(KnowledgeIndexRunItem.run_id == run.id)
    )
    assert item is not None
    assert item.status == "FAILED"
    assert item.error

    retried = await service.retry(run.id)
    assert retried.status == "PENDING"
    assert retried.failed_jobs == 0
    recovered = await service.execute(run.id, MockLLMProvider())
    assert recovered.status == "SUCCEEDED"
    assert recovered.succeeded_jobs == 1


@pytest.mark.asyncio
async def test_recovery_resets_running_items(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        job = _job("岗位职责\n负责构建 RAG 服务")
        session.add(job)
        await session.commit()
        await session.refresh(job)

        service = KnowledgeIndexService(session, MockLLMProvider())
        run = await service.create(
            KnowledgeIndexRunCreate(mode="backfill", auto_start=False)
        )
        item = await session.scalar(
            select(KnowledgeIndexRunItem).where(KnowledgeIndexRunItem.run_id == run.id)
        )
        assert item is not None
        item.status = "RUNNING"
        run.status = "RUNNING"
        await session.commit()

        monkeypatch.setattr(knowledge_indexing, "SessionLocal", factory)
        recovered_ids = await knowledge_indexing.recover_interrupted_knowledge_indexes()
        assert recovered_ids == [run.id]

        await session.refresh(run)
        await session.refresh(item)
        assert run.status == "PENDING"
        assert run.stage == "recovering"
        assert item.status == "PENDING"
    await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_index_run_api_can_create_and_inspect_items(
    client: AsyncClient,
) -> None:
    imported = await client.post(
        "/api/jobs/import",
        json={
            "mode": "single",
            "raw_jd": "AI Agent 实习生\n岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python",
            "platform": "test",
            "external_job_id": "knowledge-api-1",
            "title": "AI Agent 实习生",
        },
    )
    assert imported.status_code == 201
    job_id = imported.json()["items"][0]["job"]["id"]

    created = await client.post(
        "/api/knowledge/index-runs",
        json={"mode": "incremental", "job_ids": [job_id], "auto_start": False},
    )
    assert created.status_code == 202
    run = created.json()
    assert run["status"] == "PENDING"
    assert run["total_jobs"] == 1

    items = await client.get(f"/api/knowledge/index-runs/{run['id']}/items")
    assert items.status_code == 200
    assert items.json()["total"] == 1
    assert items.json()["items"][0]["status"] == "PENDING"
