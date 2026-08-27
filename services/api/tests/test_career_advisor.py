from __future__ import annotations

from hashlib import sha256

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm.provider import MockLLMProvider
from app.models.base import Base
from app.models.entities import Job, JobSkill, Resume, ResumeChunk
from app.schemas.career_advisor import CareerAdvisorMessageCreate, CareerAdvisorSessionCreate
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.services.career_advisor import (
    CareerAdvisorService,
    CareerAdvisorToolService,
    classify_career_intent,
)
from app.services.knowledge_indexing import KnowledgeIndexService


@pytest_asyncio.fixture
async def advisor_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


def _job() -> Job:
    description = (
        "岗位职责：负责构建 RAG 检索服务并参与 Agent 应用开发。"
        "任职要求：熟悉 Python、RAG，学历本科及以上。"
    )
    job = Job(
        platform="test",
        title="AI Agent RAG 实习生",
        description=description,
        location="北京",
        salary_min=200,
        salary_max=300,
        job_type="实习",
        education_requirement="本科及以上",
        experience_requirement="经验不限",
        source_url="https://example.com/jobs/1",
        raw_data={"company_name": "CareerPilot Labs", "salary_text": "200-300元/天"},
        normalized_data={
            "structured_job": {
                "title": "AI Agent RAG 实习生",
                "role_category": "AI Agent",
                "job_type": "实习",
                "location": "北京",
                "education_requirement": "本科及以上",
                "experience_requirement": "经验不限",
                "required_skills": ["Python", "RAG"],
                "preferred_skills": ["LangChain"],
                "responsibilities": ["负责构建 RAG 检索服务", "参与 Agent 应用开发"],
                "benefits": [],
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
    job.skills.extend(
        [
            JobSkill(skill_name="Python", skill_type="required", confidence=0.95),
            JobSkill(skill_name="RAG", skill_type="required", confidence=0.95),
            JobSkill(skill_name="LangChain", skill_type="preferred", confidence=0.8),
        ]
    )
    return job


async def _index_job(session: AsyncSession) -> Job:
    job = _job()
    session.add(job)
    await session.commit()
    service = KnowledgeIndexService(session, MockLLMProvider())
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
    result = await service.execute(run.id, MockLLMProvider())
    assert result.status == "SUCCEEDED"
    return job


def test_career_advisor_intent_classifier() -> None:
    assert classify_career_intent("北京 AI Agent 的市场需求怎么样？") == "market_research"
    assert classify_career_intent("我的简历还缺哪些技能？") == "resume_gap"
    assert classify_career_intent("给我一份 90 天学习路线") == "learning_roadmap"
    assert classify_career_intent("RAG 和后端开发哪个更适合我？") == "role_comparison"
    assert classify_career_intent("继续说说", has_context=True) == "follow_up"


@pytest.mark.asyncio
async def test_career_advisor_persists_answer_and_citations(
    advisor_session: AsyncSession,
) -> None:
    job = await _index_job(advisor_session)
    provider = MockLLMProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    session = await service.create_session(CareerAdvisorSessionCreate())

    answer = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="北京 AI Agent 通常要求哪些技能？"),
    )

    assert answer.status == "COMPLETED"
    assert answer.intent == "skill_analysis"
    assert "数据事实" in answer.content
    assert "AI 建议" in answer.content
    assert answer.answer_metadata["fact_source"] == "database"
    assert answer.citations
    assert answer.citations[0].job_id == job.id

    comparison = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="RAG 和后端开发哪个方向更适合我？"),
    )
    assert comparison.status == "COMPLETED"
    assert comparison.intent == "role_comparison"
    assert comparison.tool_trace[0]["tool"] == "compare_role_profiles"

    detail = await service.get_session(session.id)
    assert len(detail.messages) == 4
    assert detail.summary


@pytest.mark.asyncio
async def test_resume_gap_and_roadmap_use_read_only_tools(
    advisor_session: AsyncSession,
) -> None:
    await _index_job(advisor_session)
    service = CareerAdvisorService(
        advisor_session,
        MockLLMProvider(),
        embedding_provider=MockLLMProvider(),
    )
    user = await service._default_user()
    provider = MockLLMProvider()
    resume = Resume(
        user_id=user.id,
        name="测试简历",
        raw_text="Python 项目经历",
        structured_profile={"skills": ["Python"]},
    )
    resume.chunks.append(
        ResumeChunk(
            chunk_type="project",
            content="使用 Python 完成数据处理",
            embedding=await provider.embed("使用 Python 完成数据处理"),
        )
    )
    advisor_session.add(resume)
    await advisor_session.commit()

    session = await service.create_session(CareerAdvisorSessionCreate(resume_id=resume.id))
    gap = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="根据我的简历，AI Agent 还缺什么技能？"),
    )
    assert gap.intent == "resume_gap"
    assert "待补齐" in gap.content

    roadmap = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="给我制定 90 天学习路线"),
    )
    assert roadmap.intent == "learning_roadmap"
    assert "0-30" in roadmap.content

    tool_names = {
        name
        for name in dir(CareerAdvisorToolService)
        if not name.startswith("_") and callable(getattr(CareerAdvisorToolService, name))
    }
    assert "search_job_knowledge" in tool_names
    assert "analyze_resume_gap" in tool_names
    assert not {"create_campaign", "send_application", "browser_task"} & tool_names


@pytest.mark.asyncio
async def test_career_advisor_api_session_and_stream(client: AsyncClient) -> None:
    market = await client.post(
        "/api/career-advisor/market/aggregate",
        json={"query": "AI Agent", "retrieval_mode": "full_text"},
    )
    assert market.status_code == 200
    assert market.json()["sample_count"] == 0

    search = await client.post(
        "/api/career-advisor/jobs/search",
        json={"query": "AI Agent", "retrieval_mode": "full_text"},
    )
    assert search.status_code == 200
    assert search.json()["citations"] == []

    comparison = await client.post(
        "/api/career-advisor/role-comparison",
        json={"queries": ["RAG", "后端开发"]},
    )
    assert comparison.status_code == 200
    assert len(comparison.json()["reports"]) == 2

    created = await client.post("/api/career-advisor/sessions", json={})
    assert created.status_code == 201
    session_id = created.json()["id"]
    sessions = await client.get("/api/career-advisor/sessions")
    assert sessions.status_code == 200
    assert sessions.json()["total"] == 1

    message = await client.post(
        f"/api/career-advisor/sessions/{session_id}/messages",
        json={"content": "AI Agent 方向需要学习哪些技术栈？"},
    )
    assert message.status_code == 201
    assert message.json()["status"] == "COMPLETED"

    stream = await client.post(
        f"/api/career-advisor/sessions/{session_id}/messages/stream",
        json={"content": "继续给我一个学习建议"},
    )
    assert stream.status_code == 200
    assert "message_started" in stream.text
    assert "message_state" in stream.text

    citations = await client.get(
        f"/api/career-advisor/messages/{message.json()['id']}/citations"
    )
    assert citations.status_code == 200
    assert citations.json()["total"] == 0
