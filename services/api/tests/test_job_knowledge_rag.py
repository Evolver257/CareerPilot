from __future__ import annotations

from hashlib import sha256

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm.provider import MockLLMProvider
from app.models.base import Base
from app.models.entities import Job, JobSkill, KnowledgeIndexRun, Resume, ResumeChunk, User
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.schemas.knowledge_search import JobKnowledgeFilters, JobKnowledgeSearchRequest
from app.services.job_knowledge import normalize_experience_requirement
from app.services.job_knowledge_rag import (
    JobKnowledgeRAG,
    KnowledgeEmbeddingUnavailableError,
    _query_terms,
    clear_knowledge_search_cache,
    section_weights_for_query,
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


async def test_optional_cross_encoder_scores_and_cache_are_isolated(rag_session, monkeypatch):
    clear_knowledge_search_cache()
    await _index(rag_session, _job("岗位职责：开发 RAG 知识库。任职要求：熟悉 Python。"))
    calls = []

    def predict(self, query, documents):
        calls.append(query)
        return [2.0] * len(documents)

    monkeypatch.setattr("app.llm.local_semantic.SemanticReranker.predict", predict)
    rag = JobKnowledgeRAG(rag_session, MockLLMProvider())
    request = JobKnowledgeSearchRequest(query="RAG", rerank_mode="none")
    await rag.search(request)
    request = request.model_copy(update={"rerank_mode": "cross_encoder"})
    result = await rag.search(request)
    assert not result.cache_hit
    assert result.reranker == "cross_encoder"
    assert result.citations
    assert result.citations[0].fusion_score == pytest.approx(88.08, abs=0.01)
    assert (await rag.search(request)).cache_hit
    assert len(calls) == 1


async def test_query_embeddings_are_batched_and_cached(rag_session):
    clear_knowledge_search_cache()

    class CountingProvider(MockLLMProvider):
        def __init__(self):
            super().__init__()
            self.batch_calls = 0

        async def embed_many(self, texts, *, model=None):
            self.batch_calls += 1
            return await super().embed_many(texts, model=model)

    provider = CountingProvider()
    rag = JobKnowledgeRAG(rag_session, provider)
    first = await rag.embed_queries(["AI Agent 技能", "AI Agent 职责", "AI Agent 技能"])
    second = await rag.embed_queries(["AI Agent 技能", "AI Agent 职责"])

    assert set(first) == {"AI Agent 技能", "AI Agent 职责"}
    assert set(second) == set(first)
    assert provider.batch_calls == 1


@pytest.mark.asyncio
async def test_incremental_indexing_does_not_disable_stable_retrieval(rag_session):
    rag_session.add(KnowledgeIndexRun(mode="incremental", status="RUNNING"))
    await rag_session.commit()

    rag = JobKnowledgeRAG(rag_session, MockLLMProvider())

    assert await rag.knowledge_update_in_progress() is False


@pytest.mark.asyncio
async def test_full_rebuild_still_enables_temporary_fast_mode(rag_session):
    rag_session.add(KnowledgeIndexRun(mode="backfill", status="PENDING"))
    await rag_session.commit()

    rag = JobKnowledgeRAG(rag_session, MockLLMProvider())

    assert await rag.knowledge_update_in_progress() is True


@pytest.mark.asyncio
async def test_hybrid_search_only_falls_back_for_incompatible_query_dimensions(rag_session):
    await _index(rag_session, _job("岗位职责：负责 RAG 检索服务。任职要求：熟悉 Python。"))

    result = await JobKnowledgeRAG(rag_session, MockLLMProvider(dimensions=3)).search(
        JobKnowledgeSearchRequest(query="RAG", force_refresh=True)
    )

    assert result.citations
    assert any("维度不兼容" in warning for warning in result.warnings)


async def test_requested_cross_encoder_failure_is_explicit(rag_session, monkeypatch):
    from app.services.job_knowledge_rag import KnowledgeRetrievalError

    await _index(rag_session, _job("岗位职责：开发 RAG 检索。任职要求：Python。"))

    def unavailable(*args):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("app.llm.local_semantic.SemanticReranker.predict", unavailable)
    with pytest.raises(KnowledgeRetrievalError, match="未静默"):
        await JobKnowledgeRAG(rag_session, MockLLMProvider()).search(
            JobKnowledgeSearchRequest(query="RAG", rerank_mode="cross_encoder", force_refresh=True)
        )


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


def test_query_terms_keep_domain_concepts_and_drop_prompt_filler() -> None:
    terms = _query_terms("我想学习 AI Agent，需要掌握哪些技术栈？")

    assert "AI Agent" in terms
    assert "ai agent" in terms
    assert "agent" not in terms
    assert not {"学习", "需要", "哪些", "技术", "术栈"} & set(terms)
    assert _query_terms("还有其他建议吗？") == []


def test_query_terms_expand_domain_paraphrases_and_section_weights_follow_intent() -> None:
    assert {"Linux", "Shell", "Bash"} <= set(_query_terms("熟悉企鹅操作系统命令行的岗位"))
    assert {"模型评测", "评测集", "评估体系"} <= set(_query_terms("哪些岗位需要验证生成答案质量"))

    education = section_weights_for_query("这些岗位要求什么学历？")
    salary = section_weights_for_query("岗位薪资待遇如何？")

    assert education["education"] > education["responsibilities"]
    assert salary["salary_benefits"] > salary["required_skills"]


def test_experience_normalization_never_returns_free_form_requirements() -> None:
    assert normalize_experience_requirement("经验不限") == "应届/经验不限"
    assert normalize_experience_requirement("具备 1-3 年 Python 开发经验") == "1-3年"
    assert normalize_experience_requirement("至少 3 年相关经验") == "3-5年"
    assert normalize_experience_requirement("5年以上大模型研发经验") == "5年以上"
    assert normalize_experience_requirement("2027年及以后毕业的优秀硕博研究生") == ""
    assert normalize_experience_requirement("具备大规模分布式系统检索的经验") == ""


@pytest.mark.asyncio
async def test_natural_language_query_excludes_generic_unrelated_jobs(
    rag_session: AsyncSession,
) -> None:
    clear_knowledge_search_cache()
    relevant = _job(
        "负责 AI Agent 与 RAG 应用开发，熟悉 Python",
        title="AI Agent 开发实习生",
    )
    unrelated = _job(
        "负责商家拓展，需要持续学习业务知识并提供运营建议",
        title="商家 BD 实习生",
    )
    unrelated.normalized_data = {
        "structured_job": {
            "title": unrelated.title,
            "role_category": "Sales",
            "job_type": "实习",
            "location": "北京",
            "education_requirement": "本科及以上",
            "experience_requirement": "经验不限",
            "required_skills": [],
            "preferred_skills": [],
            "responsibilities": ["负责商家拓展和运营"],
            "benefits": [],
        },
        "requirements": {
            "education": "本科及以上",
            "experience": "经验不限",
            "responsibilities": ["负责商家拓展和运营"],
            "qualifications": ["沟通能力良好"],
            "preferred_qualifications": [],
        },
    }
    await _index(rag_session, relevant, unrelated)

    result = await JobKnowledgeRAG(rag_session, MockLLMProvider()).search(
        JobKnowledgeSearchRequest(
            query="我想学习 AI Agent，需要掌握哪些技术栈？",
            retrieval_mode="full_text",
            top_k=10,
        )
    )

    assert result.sample_count == 1
    assert {citation.job_id for citation in result.citations} == {relevant.id}


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
