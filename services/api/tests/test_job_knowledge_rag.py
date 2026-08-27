from __future__ import annotations

from hashlib import sha256

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm.provider import MockLLMProvider
from app.models.base import Base
from app.models.entities import Job, JobSkill, Resume, ResumeChunk, User
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.schemas.knowledge_search import JobKnowledgeFilters, JobKnowledgeSearchRequest
from app.services.job_knowledge_rag import (
    JobKnowledgeRAG,
    KnowledgeEmbeddingUnavailableError,
    clear_knowledge_search_cache,
)
from app.services.knowledge_indexing import KnowledgeIndexService


@pytest_asyncio.fixture
async def rag_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


def _job(
    description: str,
    *,
    title: str = "RAG 应用实习生",
    city: str = "北京",
    company_name: str = "Knowledge Labs",
) -> Job:
    return Job(
        platform="test",
        title=title,
        description=description,
        location=city,
        salary_min=180,
        salary_max=260,
        job_type="实习",
        education_requirement="本科及以上",
        experience_requirement="经验不限",
        raw_data={"company_name": company_name, "salary_text": "180-260元/天"},
        normalized_data={
            "structured_job": {
                "title": title,
                "role_category": "AI Agent",
                "job_type": "实习",
                "location": city,
                "education_requirement": "本科及以上",
                "experience_requirement": "经验不限",
                "required_skills": ["Python", "RAG"],
                "preferred_skills": ["LangChain"],
                "responsibilities": ["负责构建 RAG 检索服务", "参与 Agent 应用开发"],
                "benefits": ["导师指导"],
            },
            "requirements": {
                "education": "本科及以上",
                "experience": "经验不限",
                "responsibilities": ["负责构建 RAG 检索服务"],
                "qualifications": ["熟悉 Python 和 RAG"],
                "preferred_qualifications": ["了解 LangChain"],
            },
        },
        content_hash=sha256(description.encode("utf-8")).hexdigest(),
    )


async def _index(session: AsyncSession, *jobs: Job) -> None:
    session.add_all(jobs)
    await session.commit()
    service = KnowledgeIndexService(session, MockLLMProvider())
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
    completed = await service.execute(run.id, MockLLMProvider())
    assert completed.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_hybrid_search_returns_citations_and_sql_statistics(
    rag_session: AsyncSession,
) -> None:
    clear_knowledge_search_cache()
    job = _job("岗位职责\n负责构建 RAG 检索服务\n任职要求\n熟悉 Python 和 LangChain")
    job.skills.extend(
        [
            JobSkill(skill_name="RAG", skill_type="required", confidence=0.95),
            JobSkill(skill_name="Python", skill_type="required", confidence=0.95),
            JobSkill(skill_name="LangChain", skill_type="preferred", confidence=0.8),
        ]
    )
    await _index(rag_session, job)

    result = await JobKnowledgeRAG(rag_session, MockLLMProvider()).search(
        JobKnowledgeSearchRequest(query="RAG Agent", top_k=5)
    )

    assert result.sample_count == 1
    assert result.statistics.salary_bands[0].unit == "cny_day"
    assert result.statistics.education_distribution[0].label == "本科及以上"
    assert {skill.name for skill in result.statistics.skills} >= {"RAG", "Python"}
    assert result.citations
    assert result.citations[0].job_id == job.id
    assert result.citations[0].chunk_id
    assert result.citations[0].evidence
    assert {"full_text", "vector"} <= set(result.citations[0].retrieval_sources)
    assert result.cache_hit is False

    cached = await JobKnowledgeRAG(rag_session, MockLLMProvider()).search(
        JobKnowledgeSearchRequest(query="RAG Agent", top_k=5)
    )
    assert cached.cache_hit is True

    alias_result = await JobKnowledgeRAG(rag_session, MockLLMProvider()).search(
        JobKnowledgeSearchRequest(
            query="检索增强生成",
            retrieval_mode="full_text",
            top_k=5,
        )
    )
    assert alias_result.citations[0].job_id == job.id


@pytest.mark.asyncio
async def test_metadata_filter_limits_sample_and_vector_results(
    rag_session: AsyncSession,
) -> None:
    beijing = _job("RAG 岗位职责\n负责北京团队的检索增强服务", city="北京")
    shanghai = _job(
        "RAG 岗位职责\n负责上海团队的检索增强服务",
        title="RAG 后端实习生",
        city="上海",
        company_name="Other Labs",
    )
    await _index(rag_session, beijing, shanghai)

    result = await JobKnowledgeRAG(rag_session, MockLLMProvider()).search(
        JobKnowledgeSearchRequest(
            query="RAG",
            filters=JobKnowledgeFilters(cities=["北京"]),
            retrieval_mode="vector",
            top_k=10,
        )
    )

    assert result.sample_count == 1
    assert {citation.location for citation in result.citations} == {"北京"}


@pytest.mark.asyncio
async def test_search_can_attach_resume_rag_evidence(
    rag_session: AsyncSession,
) -> None:
    job = _job("岗位职责\n负责构建 RAG 检索服务\n任职要求\n熟悉 Python")
    await _index(rag_session, job)
    user = User(email="rag@example.com", name="RAG User")
    rag_session.add(user)
    await rag_session.flush()
    provider = MockLLMProvider()
    resume = Resume(
        user_id=user.id,
        name="RAG Resume",
        raw_text="Python RAG project",
        structured_profile={"skills": ["Python", "RAG"]},
    )
    resume.chunks.append(
        ResumeChunk(
            chunk_type="project",
            content="Built a Python RAG retrieval service",
            embedding=await provider.embed("Built a Python RAG retrieval service"),
            chunk_metadata={"source": "test"},
        )
    )
    rag_session.add(resume)
    await rag_session.commit()
    await rag_session.refresh(resume)

    result = await JobKnowledgeRAG(rag_session, provider).search(
        JobKnowledgeSearchRequest(
            query="RAG",
            resume_id=resume.id,
            include_resume_evidence=True,
            top_k=5,
        )
    )

    assert result.resume_evidence
    assert result.resume_evidence[0].job_id == job.id
    assert "RAG" in result.resume_evidence[0].content


@pytest.mark.asyncio
async def test_vector_mode_reports_missing_embedding_provider(
    rag_session: AsyncSession,
) -> None:
    await _index(rag_session, _job("岗位职责\n负责 RAG 服务"))

    with pytest.raises(KnowledgeEmbeddingUnavailableError, match="Embedding Provider"):
        await JobKnowledgeRAG(rag_session).search(
            JobKnowledgeSearchRequest(query="RAG", retrieval_mode="vector")
        )


@pytest.mark.asyncio
async def test_knowledge_search_api_returns_empty_state(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/api/knowledge/search",
        json={"query": "RAG", "retrieval_mode": "full_text"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 0
    assert body["citations"] == []
    assert body["warnings"]

    statistics = await client.post(
        "/api/knowledge/statistics",
        json={"query": "RAG", "retrieval_mode": "full_text"},
    )
    assert statistics.status_code == 200
    assert statistics.json()["sample_count"] == 0
