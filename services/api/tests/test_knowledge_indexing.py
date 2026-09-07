from __future__ import annotations

from hashlib import sha256

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm.provider import MockLLMProvider
from app.llm.tokenization import CallableTokenCounter
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
from app.schemas.job_intelligence import JobImportRequest
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.services import knowledge_indexing
from app.services.job_knowledge import (
    JOB_KNOWLEDGE_CHUNK_CHAR_LIMIT,
    JOB_KNOWLEDGE_CHUNK_TOKEN_LIMIT,
    build_job_knowledge_chunks,
    canonicalize_skill,
    estimate_knowledge_tokens,
)
from app.services.jobs import JobService
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
    required = "\n".join(
        draft.content for draft in drafts if draft.section_type == "required_skills"
    )
    preferred = "\n".join(
        draft.content for draft in drafts if draft.section_type == "preferred_skills"
    )
    assert "技能：Python；原文要求：熟悉 Python，了解 Torch" in required
    assert "加分技能：PyTorch；原文要求：熟悉 Python，了解 Torch" in preferred
    assert canonicalize_skill("Torch") == "PyTorch"


def test_chunker_preserves_unparsed_source_and_filters_section_headings() -> None:
    job = _job("岗位职责\n维护现有服务\n任职要求\n精通 Kubernetes 并能独立排查集群问题")
    job.normalized_data = {
        "structured_job": {"required_skills": ["Python"]},
        "requirements": {"responsibilities": ["维护现有服务"]},
    }

    drafts = build_job_knowledge_chunks(job)
    source = "\n".join(draft.content for draft in drafts if draft.section_type == "source_context")

    assert "精通 Kubernetes 并能独立排查集群问题" in source
    assert "- 岗位职责" not in source
    assert "- 任职要求" not in source
    assert "维护现有服务" not in source


def test_chunker_respects_embedding_token_budget_for_long_single_line() -> None:
    long_requirement = "".join(
        f"第{index}项要求精通Python并完成复杂模块设计、性能优化及故障排查。"
        for index in range(30)
    )
    job = _job(f"任职要求\n{long_requirement}")
    job.normalized_data = {
        "structured_job": {"required_skills": ["Python"]},
        "requirements": {"qualifications": [long_requirement]},
    }

    drafts = build_job_knowledge_chunks(job)

    assert len([draft for draft in drafts if draft.section_type == "requirements"]) > 1
    assert len([draft for draft in drafts if draft.section_type == "required_skills"]) == 1
    assert all(len(draft.content) <= JOB_KNOWLEDGE_CHUNK_CHAR_LIMIT for draft in drafts)
    assert all(draft.token_count <= JOB_KNOWLEDGE_CHUNK_TOKEN_LIMIT for draft in drafts)
    assert all(draft.token_count == estimate_knowledge_tokens(draft.content) for draft in drafts)


def test_chunker_uses_provider_token_counter_and_records_provenance() -> None:
    counter = CallableTokenCounter(
        callback=len,
        signature="test:character-tokenizer-v1",
        exact=True,
    )
    long_requirement = "需要完成复杂模块设计、性能优化以及线上故障排查。" * 20
    job = _job(f"任职要求\n{long_requirement}")
    job.normalized_data = {
        "structured_job": {},
        "requirements": {"qualifications": [long_requirement]},
    }

    drafts = build_job_knowledge_chunks(job, token_counter=counter)

    assert drafts
    assert all(draft.token_count == len(draft.content) for draft in drafts)
    assert all(draft.token_count <= JOB_KNOWLEDGE_CHUNK_TOKEN_LIMIT for draft in drafts)
    assert all(
        draft.metadata["tokenizer_signature"] == "test:character-tokenizer-v1"
        for draft in drafts
    )
    assert all(draft.metadata["token_count_exact"] is True for draft in drafts)


def test_chunker_deduplicates_skill_aliases_after_enrichment() -> None:
    job = _job("任职要求\n熟悉 Torch 或 PyTorch")
    job.normalized_data["structured_job"]["required_skills"] = ["Torch", "PyTorch"]

    drafts = build_job_knowledge_chunks(job)
    keys = [(draft.section_type, draft.content_hash) for draft in drafts]
    required = [draft for draft in drafts if draft.section_type == "required_skills"]

    assert len(keys) == len(set(keys))
    assert len(required) == 1
    assert "技能：PyTorch" in required[0].content


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
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
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
    assert all(len(chunk.embedding or []) == 1024 for chunk in chunks)

    facts = list(
        (await session.scalars(select(JobSkillFact).where(JobSkillFact.job_id == job.id))).all()
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

    second_run = await service.create(KnowledgeIndexRunCreate(mode="incremental", auto_start=False))
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
        (await session.scalars(select(JobVersion).where(JobVersion.job_id == job.id))).all()
    )
    assert len(versions) == 2
    assert sum(version.is_current for version in versions) == 1


@pytest.mark.asyncio
async def test_health_reports_legacy_embedding_as_needs_update(session: AsyncSession) -> None:
    job = _job("岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python")
    session.add(job)
    await session.commit()

    legacy_provider = MockLLMProvider()
    legacy_provider.embedding_signature = "legacy-minilm:384"
    service = KnowledgeIndexService(session, legacy_provider)
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
    completed = await service.execute(run.id, legacy_provider)
    assert completed.status == "SUCCEEDED"

    current_provider = MockLLMProvider()
    current_provider.embedding_signature = "current-qwen:1024"
    health = await KnowledgeIndexService(session, current_provider).health()
    assert health["status"] == "needs_update"
    assert health["ready"] is False
    assert health["indexed_jobs"] == 1
    assert health["compatible_jobs"] == 0
    assert health["needs_update_jobs"] == 1

    incremental = await KnowledgeIndexService(session, current_provider).create(
        KnowledgeIndexRunCreate(mode="incremental", auto_start=False)
    )
    assert incremental.total_jobs == 1


@pytest.mark.asyncio
async def test_index_deduplicates_same_section_and_content_hash(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job("岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python")
    drafts = build_job_knowledge_chunks(job)
    assert drafts
    monkeypatch.setattr(
        knowledge_indexing,
        "build_job_knowledge_chunks",
        lambda _job, **_kwargs: [drafts[0], drafts[0]],
    )
    session.add(job)
    await session.commit()

    service = KnowledgeIndexService(session, MockLLMProvider())
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
    completed = await service.execute(run.id, MockLLMProvider())

    assert completed.status == "SUCCEEDED"
    chunks = list(
        (
            await session.scalars(
                select(JobKnowledgeChunk).where(JobKnowledgeChunk.job_id == job.id)
            )
        ).all()
    )
    assert len(chunks) == 1


@pytest.mark.asyncio
async def test_index_stores_only_canonical_experience_bucket(session: AsyncSession) -> None:
    job = _job("岗位职责\n负责 Agent 开发\n任职要求\n有大模型项目经验")
    job.experience_requirement = "具备大规模分布式系统检索的经验"
    job.normalized_data["structured_job"]["experience_requirement"] = (
        "技术能力：熟练 Java，具备扎实计算机基础"
    )
    session.add(job)
    await session.commit()

    service = KnowledgeIndexService(session, MockLLMProvider())
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
    completed = await service.execute(run.id, MockLLMProvider())
    document = await session.scalar(
        select(JobKnowledgeDocument).where(JobKnowledgeDocument.job_id == job.id)
    )

    assert completed.status == "SUCCEEDED"
    assert document is not None
    assert document.normalized_experience == ""


@pytest.mark.asyncio
async def test_failed_index_can_be_retried_from_persisted_item(session: AsyncSession) -> None:
    job = _job("岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    service = KnowledgeIndexService(session, MockLLMProvider())
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
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
    monkeypatch.setattr(knowledge_indexing.get_settings(), "independent_worker", False)
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
        run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
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


@pytest.mark.asyncio
async def test_job_import_persists_incremental_knowledge_run(
    session: AsyncSession,
) -> None:
    service = JobService(session)
    result = await service.import_jobs(
        JobImportRequest(
            mode="single",
            raw_jd="岗位职责\n负责构建 RAG 服务\n任职要求\n熟悉 Python",
            platform="test",
            external_job_id="auto-index-job",
            title="AI Agent 实习生",
            location="北京",
        )
    )

    run = await session.scalar(
        select(knowledge_indexing.KnowledgeIndexRun).order_by(
            knowledge_indexing.KnowledgeIndexRun.created_at.desc()
        )
    )
    assert result.created == 1
    assert run is not None
    assert run.mode == "incremental"
    assert run.status == "PENDING"
    assert run.total_jobs == 1
    item = await session.scalar(
        select(KnowledgeIndexRunItem).where(KnowledgeIndexRunItem.run_id == run.id)
    )
    assert item is not None
    assert item.job_id == result.jobs[0].id
