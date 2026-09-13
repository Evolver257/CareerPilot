from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.llm.provider import MockLLMProvider
from app.models.base import Base
from app.models.entities import Job, JobSkill, KnowledgeIndexRun
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.schemas.knowledge_search import (
    JobKnowledgeCitation,
    JobKnowledgeFilters,
    JobKnowledgeSearchRequest,
    RAGEvidence,
    RAGEvidenceSource,
    RAGPlannerPlan,
    RAGRetrievalQuery,
    RAGVerification,
)
from app.services.agentic_rag import (
    AgenticRAGPipeline,
    AnswerVerifier,
    ContextBuilder,
    EvidenceDeduplicator,
    EvidenceEvaluator,
    QueryAnalyzer,
    QueryRewriter,
    RAGBudgetLedger,
    Reranker,
    RetrievalCandidate,
    RetrievalPlanner,
    _merge_similar_queries,
    _select_job_diverse_candidates,
)
from app.services.job_knowledge_rag import JobKnowledgeRAG
from app.services.knowledge_indexing import KnowledgeIndexService
from app.services.rag_planning import (
    AnswerReflectionService,
    RetrievalPlanValidator,
    clear_rag_planner_cache,
)


@pytest_asyncio.fixture
async def agentic_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


def _job(
    title: str,
    description: str,
    *,
    company: str,
    complete: bool = True,
) -> Job:
    structured = {
        "title": title,
        "role_category": "AI Agent",
        "job_type": "实习",
        "location": "北京",
        "required_skills": ["Python", "RAG"],
        "preferred_skills": ["LangGraph"],
        "responsibilities": ["构建 RAG 检索服务", "开发可恢复的 Agent 工作流"],
    }
    requirements = {
        "responsibilities": ["构建 RAG 检索服务"],
        "qualifications": ["熟悉 Python 和 RAG"],
        "preferred_qualifications": ["了解 LangGraph"],
    }
    if complete:
        structured.update(
            {
                "education_requirement": "本科及以上",
                "experience_requirement": "经验不限",
            }
        )
        requirements.update({"education": "本科及以上", "experience": "经验不限"})
    job = Job(
        platform="test",
        title=title,
        description=description,
        location="北京",
        salary_min=200 if complete else None,
        salary_max=300 if complete else None,
        job_type="实习",
        education_requirement="本科及以上" if complete else None,
        experience_requirement="经验不限" if complete else None,
        raw_data={"company_name": company, "salary_text": "200-300元/天" if complete else ""},
        normalized_data={"structured_job": structured, "requirements": requirements},
        content_hash=sha256(description.encode()).hexdigest(),
    )
    job.skills.extend(
        [
            JobSkill(skill_name="Python", skill_type="required", confidence=0.95),
            JobSkill(skill_name="RAG", skill_type="required", confidence=0.95),
            JobSkill(skill_name="LangGraph", skill_type="preferred", confidence=0.8),
        ]
    )
    return job


def _robot_job() -> Job:
    description = (
        "机器人控制算法实习生。负责 Whole Body Control、PPO 强化学习、"
        "Sim2Real、运动重定向、仿真训练和真机验证。"
        "要求硕士及以上学历，熟悉 C++、Python、ROS、控制理论和 PyTorch。"
    )
    job = Job(
        platform="test",
        title="机器人控制算法实习生",
        description=description,
        location="武汉",
        salary_min=250,
        salary_max=350,
        job_type="实习",
        education_requirement="硕士及以上",
        experience_requirement="经验不限",
        raw_data={"company_name": "Robot Lab", "salary_text": "250-350元/天"},
        normalized_data={
            "structured_job": {
                "title": "机器人控制算法实习生",
                "role_category": "机器人控制",
                "job_type": "实习",
                "location": "武汉",
                "education_requirement": "硕士及以上",
                "experience_requirement": "经验不限",
                "required_skills": ["C++", "Python", "ROS", "PyTorch"],
                "preferred_skills": ["PPO", "Sim2Real"],
                "responsibilities": [
                    "研发 Whole Body Control",
                    "完成仿真训练和真机验证",
                ],
            },
            "requirements": {
                "responsibilities": ["研发机器人全身运动控制算法"],
                "qualifications": ["硕士及以上学历", "熟悉 C++、Python 和 ROS"],
                "preferred_qualifications": ["具备 PPO 和 Sim2Real 项目经验"],
                "education": "硕士及以上",
                "experience": "经验不限",
            },
        },
        content_hash=sha256(description.encode()).hexdigest(),
    )
    job.skills.extend(
        [
            JobSkill(skill_name="C++", skill_type="required", confidence=0.98),
            JobSkill(skill_name="Python", skill_type="required", confidence=0.95),
            JobSkill(skill_name="ROS", skill_type="required", confidence=0.95),
            JobSkill(skill_name="PyTorch", skill_type="required", confidence=0.9),
        ]
    )
    return job


async def _index(session: AsyncSession, *jobs: Job) -> None:
    session.add_all(jobs)
    await session.commit()
    service = KnowledgeIndexService(session, MockLLMProvider())
    run = await service.create(KnowledgeIndexRunCreate(mode="backfill", auto_start=False))
    completed = await service.execute(run.id, MockLLMProvider())
    assert completed.status == "SUCCEEDED"


def test_query_analysis_and_rewrite_are_structured_and_bounded() -> None:
    settings = Settings(rag_max_queries=6)
    analysis = QueryAnalyzer().analyze(
        "比较 LangGraph 和 AutoGen 的状态管理机制，并说明如何学习",
        intent="role_comparison",
    )
    rewrite = QueryRewriter(settings).rewrite(analysis)

    assert analysis.question_type == "comparison"
    assert analysis.complexity == "complex"
    assert "comparison_dimensions" in analysis.required_information
    assert len(analysis.entities) >= 2
    assert 1 <= len(rewrite.all_queries) <= 6
    assert rewrite.semantic_query == analysis.original_query
    assert rewrite.all_queries[0] == analysis.original_query


def test_procedural_rewrite_keeps_responsibility_query_within_first_round_budget() -> None:
    settings = Settings(rag_max_queries=6)
    analysis = QueryAnalyzer().analyze("AI Agent 岗位应该如何学习和准备？")

    rewrite = QueryRewriter(settings).rewrite(analysis)

    # The pipeline executes at most four queries in the first round so it can
    # reserve budget for repair. Required dimensions must not be crowded out
    # by broad exact/keyword rewrites.
    first_round = rewrite.all_queries[:4]
    assert any("岗位职责 工作内容" in query for query in first_round)


def test_similar_query_rewrites_are_merged_before_embedding() -> None:
    queries = _merge_similar_queries(
        ["AI Agent 岗位需要哪些技能", "AI Agent 岗位的技能要求", "机器人控制算法岗位"],
        6,
    )

    assert len(queries) == 2
    assert queries[0] == "AI Agent 岗位需要哪些技能"
    assert "AI Agent 岗位的技能要求" not in queries


def test_agentic_candidate_pool_keeps_distinct_jobs_before_supporting_chunks() -> None:
    first_job = uuid4()
    other_jobs = [uuid4(), uuid4()]

    def candidate(job_id, rank):
        return RetrievalCandidate(
            citation=JobKnowledgeCitation(
                citation_index=rank,
                job_id=job_id,
                chunk_id=uuid4(),
                title=f"岗位 {rank}",
                platform="test",
                section_type="requirements",
                evidence="任职要求",
                lexical_score=0,
                semantic_score=0,
                fusion_score=0,
                rank=rank,
            ),
            rerank_score=1 - rank / 10,
        )

    ranked = [
        candidate(first_job, 1),
        candidate(first_job, 2),
        candidate(other_jobs[0], 3),
        candidate(other_jobs[1], 4),
    ]

    selected = _select_job_diverse_candidates(ranked, 3)

    assert [item.citation.job_id for item in selected] == [first_job, *other_jobs]


def test_rag_budget_reserves_failed_attempts_before_execution() -> None:
    budget = RAGBudgetLedger(
        max_tool_calls=1,
        max_search_calls=1,
        max_llm_calls=1,
        max_tokens=1000,
    )

    assert budget.reserve("search") is True
    # No success/commit call is needed: the attempt has already consumed the
    # budget and a retry cannot bypass the hard limit.
    assert budget.reserve("search") is False
    assert budget.snapshot()["tool_calls_used"] == 1
    assert budget.snapshot()["exhausted_reason"] == "tool_call_budget_exhausted"


@pytest.mark.asyncio
async def test_indexing_run_switches_agentic_rag_to_one_full_text_query(
    agentic_session: AsyncSession,
) -> None:
    agentic_session.add(KnowledgeIndexRun(mode="backfill", status="RUNNING"))
    await agentic_session.commit()
    pipeline = AgenticRAGPipeline(JobKnowledgeRAG(agentic_session, MockLLMProvider()))

    result = await pipeline.run(JobKnowledgeSearchRequest(query="AI Agent 岗位需要哪些技能？"))

    assert result.retrieval_plan.strategy == "full_text"
    assert result.retrieval_plan.max_iterations == 1
    assert result.trace.query_count == 1
    assert result.trace.knowledge_execution_mode == "fast"
    assert result.trace.agentic_capability_level == "fast"
    assert result.trace.budget["search_calls_used"] == 1
    assert any("单次快速全文检索" in item for item in result.trace.degradations)


def test_agentic_planner_keeps_unparsed_source_context_for_skill_queries() -> None:
    analysis = QueryAnalyzer().analyze("AI Agent 如何学习，需要哪些技能？")
    plan = RetrievalPlanner(Settings()).plan(analysis, JobKnowledgeFilters())

    assert "source_context" in plan.section_types


def test_llm_plan_validator_preserves_user_filters() -> None:
    settings = Settings(rag_planner_confidence_threshold=0.55)
    fallback = RetrievalPlanner(settings).plan(
        QueryAnalyzer().analyze("比较 AI Agent 岗位的技能和学历"),
        JobKnowledgeFilters(cities=["北京"]),
    )
    candidate = RAGPlannerPlan(
        queries=[RAGRetrievalQuery(query="北京 AI Agent 岗位技能和学历")],
        confidence=0.95,
        preferred_channels=["lexical", "dense"],
        hard_filters=JobKnowledgeFilters(),
    )

    plan = RetrievalPlanValidator(settings).validate(
        candidate,
        fallback=fallback,
        filters=JobKnowledgeFilters(cities=["北京"]),
    )

    assert plan.planner_source == "llm"
    assert plan.hard_filters.cities == ["北京"]
    assert plan.metadata_filter["cities"] == ["北京"]


def test_evidence_evaluator_rejects_low_relevance_semantic_neighbors() -> None:
    source = RAGEvidenceSource(
        job_id="00000000-0000-0000-0000-000000000001",
        chunk_id="00000000-0000-0000-0000-000000000011",
        title="通用开发岗位",
        section="requirements",
    )
    evidence = RAGEvidence(
        evidence_id="nearby",
        topic="requirements",
        claim="熟悉 Python 和常见 Web 开发框架",
        evidence_text="熟悉 Python 和常见 Web 开发框架。",
        relevance_score=0.31,
        source_rank=1,
        sources=[source],
    )
    analysis = QueryAnalyzer().analyze("量子计算岗位需要哪些技能？")

    result = EvidenceEvaluator(Settings(rag_evidence_min_relevance=0.42)).evaluate(
        analysis, [evidence]
    )

    assert result.max_relevance_score == pytest.approx(0.31)
    assert result.answerable is False


@pytest.mark.asyncio
async def test_agentic_pipeline_builds_evidence_context_and_real_citations(
    agentic_session: AsyncSession,
) -> None:
    first = _job(
        "AI Agent 实习生",
        "负责构建 RAG 检索服务，要求熟悉 Python 和 RAG",
        company="Evidence One",
    )
    second = _job(
        "大模型应用实习生",
        "参与 Agent 工作流开发，要求熟悉 Python 和 RAG",
        company="Evidence Two",
    )
    await _index(agentic_session, first, second)
    provider = MockLLMProvider()
    pipeline = AgenticRAGPipeline(JobKnowledgeRAG(agentic_session, provider))

    result = await pipeline.run(
        JobKnowledgeSearchRequest(query="AI Agent 应该如何学习，需要哪些技能？")
    )

    assert result.query_analysis.question_type == "procedural"
    assert result.trace.query_count <= 6
    assert result.trace.candidate_count >= result.trace.reranked_count
    assert result.evidence
    assert result.context.startswith("EVIDENCE_CONTEXT")
    assert result.search.citations
    evidence_chunks = {source.chunk_id for item in result.evidence for source in item.sources}
    assert {item.chunk_id for item in result.search.citations} <= evidence_chunks
    assert all(item.document_id and item.parent_id for item in result.search.citations)
    assert all("evidence_pipeline" in item.retrieval_sources for item in result.search.citations)


@pytest.mark.asyncio
async def test_narrow_role_query_keeps_statistics_and_evidence_on_target(
    agentic_session: AsyncSession,
) -> None:
    robot = _robot_job()
    unrelated = _job(
        "AI Agent 算法实习生",
        "负责 LLM、RAG 和工具调用工作流开发",
        company="Agent Lab",
    )
    await _index(agentic_session, robot, unrelated)
    pipeline = AgenticRAGPipeline(JobKnowledgeRAG(agentic_session, MockLLMProvider()))

    result = await pipeline.run(
        JobKnowledgeSearchRequest(query="机器人控制算法实习生需要哪些核心技能和学历要求？")
    )

    assert result.query_analysis.role_entities == ["机器人控制算法实习生"]
    assert result.query_analysis.question_type == "multi_hop"
    assert result.search.sample_count == 1
    assert {item.title for item in result.search.citations} == {"机器人控制算法实习生"}
    assert result.evidence_evaluation.answerable is True
    assert "education" not in result.evidence_evaluation.missing_information
    assert any("硕士" in f"{item.claim} {item.evidence_text}" for item in result.evidence)


@pytest.mark.asyncio
async def test_narrow_role_query_does_not_substitute_generic_jobs(
    agentic_session: AsyncSession,
) -> None:
    await _index(
        agentic_session,
        _job(
            "AI Agent 算法实习生",
            "负责 LLM、RAG 和工具调用工作流开发",
            company="Agent Lab",
        ),
    )
    pipeline = AgenticRAGPipeline(JobKnowledgeRAG(agentic_session, MockLLMProvider()))

    result = await pipeline.run(
        JobKnowledgeSearchRequest(query="量子交易算法实习生需要哪些核心技能和学历要求？")
    )

    assert result.query_analysis.role_entities == ["量子交易算法实习生"]
    assert result.search.sample_count == 0
    assert result.search.citations == []
    assert result.evidence == []
    assert result.knowledge_status == "insufficient"
    assert any("拒绝使用泛岗位结果" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_insufficient_evidence_runs_bounded_iterative_retrieval(
    agentic_session: AsyncSession,
) -> None:
    await _index(
        agentic_session,
        _job(
            "Agent 工程实习生",
            "负责 Agent 工具调用，要求熟悉 Python 和 RAG",
            company="Partial Evidence",
            complete=False,
        ),
    )
    settings = Settings(rag_max_iterations=2, rag_max_queries=6)
    pipeline = AgenticRAGPipeline(
        JobKnowledgeRAG(agentic_session, MockLLMProvider(), settings),
        settings=settings,
    )

    result = await pipeline.run(
        JobKnowledgeSearchRequest(query="分析 Agent 岗位的薪资、学历、经验、技能和工作职责")
    )

    assert result.trace.retrieval_iterations == 2
    assert result.trace.query_count <= 6
    assert result.trace.knowledge_execution_mode == "agentic"
    assert result.trace.agentic_capability_level == "retrieval_only"
    assert result.trace.budget["tool_calls_used"] <= result.trace.budget["tool_calls_limit"]
    assert result.knowledge_status in {"partial", "insufficient"}
    assert result.evidence_evaluation.answerable is False
    assert result.evidence_evaluation.missing_information
    assert any("当前证据不足" in warning for warning in result.warnings)


def test_evidence_deduplication_merges_sources_and_detects_conflicts() -> None:
    first_source = RAGEvidenceSource(
        job_id="00000000-0000-0000-0000-000000000001",
        chunk_id="00000000-0000-0000-0000-000000000011",
        title="岗位 A",
        section="requirements",
    )
    second_source = RAGEvidenceSource(
        job_id="00000000-0000-0000-0000-000000000002",
        chunk_id="00000000-0000-0000-0000-000000000022",
        title="岗位 B",
        section="requirements",
    )
    first = RAGEvidence(
        evidence_id="ev_1",
        topic="requirements",
        claim="网络请求失败后最多重试 3 次",
        evidence_text="最多重试 3 次",
        relevance_score=0.9,
        source_rank=1,
        sources=[first_source],
    )
    duplicate = first.model_copy(update={"evidence_id": "ev_2", "sources": [second_source]})
    conflicting = RAGEvidence(
        evidence_id="ev_3",
        topic="requirements",
        claim="网络请求失败后最多重试 5 次",
        evidence_text="最多重试 5 次",
        relevance_score=0.8,
        source_rank=2,
        sources=[second_source],
    )

    deduplicated = EvidenceDeduplicator().deduplicate([], [first, duplicate], 10)
    assert len(deduplicated) == 1
    assert len(deduplicated[0].sources) == 2

    analysis = QueryAnalyzer().analyze("网络请求失败后最多重试几次")
    evaluation = EvidenceEvaluator(Settings()).evaluate(analysis, [first, conflicting])
    assert evaluation.conflicts


def test_context_builder_prioritizes_evidence_and_honors_budget() -> None:
    source = RAGEvidenceSource(
        job_id="00000000-0000-0000-0000-000000000001",
        chunk_id="00000000-0000-0000-0000-000000000011",
        title="岗位 A",
        section="requirements",
    )
    evidence = [
        RAGEvidence(
            evidence_id="primary",
            topic="requirements",
            claim="必须掌握 Python",
            evidence_text="必须掌握 Python 并能够编写可靠的服务。",
            relevance_score=0.95,
            source_rank=1,
            sources=[source],
        ),
        RAGEvidence(
            evidence_id="background",
            topic="other",
            claim="团队使用敏捷流程",
            evidence_text="团队日常使用敏捷流程。",
            relevance_score=0.3,
            source_rank=2,
            sources=[source],
        ),
    ]

    context = ContextBuilder(Settings(rag_context_max_tokens=1000)).build(evidence)

    assert "tier=PRIMARY" in context
    assert context.index("必须掌握 Python") < context.index("团队使用敏捷流程")


@pytest.mark.asyncio
async def test_answer_reflection_uses_compact_model_contract() -> None:
    class ReflectionProvider(MockLLMProvider):
        provider_name = "openai"
        supports_streaming = True
        supports_agentic_rag_planning = True

        def __init__(self) -> None:
            super().__init__()
            self.schema_name = ""

        async def generate_structured(self, prompt, schema, **kwargs):
            del prompt, kwargs
            self.schema_name = schema.__name__
            return schema(
                status="repairable",
                repair_strategy="qualify_claim",
                unsupported_claims=[
                    {"claim": "市场覆盖率为 90%", "reason": "证据未提供该指标"}
                ],
                confidence=0.9,
            )

    provider = ReflectionProvider()
    service = AnswerReflectionService(provider, Settings())
    reflection, _, warning = await service.reflect(
        "市场覆盖率为 90%",
        RAGVerification(
            groundedness="partially_supported",
            completeness="partial",
            citation_correctness="partial",
            unsupported_claims=["市场覆盖率为 90%"],
        ),
        [],
    )

    assert provider.schema_name == "_LLMAnswerReflectionDecision"
    assert reflection.unsupported_claims[0].claim == "市场覆盖率为 90%"
    assert warning is None


class FailingReranker(Reranker):
    async def rerank(self, query, candidates, limit):
        raise RuntimeError("reranker unavailable")


@pytest.mark.asyncio
async def test_agentic_pipeline_uses_llm_plan_and_reflects_evidence_gap(
    agentic_session: AsyncSession,
) -> None:
    clear_rag_planner_cache()

    class PlanningProvider(MockLLMProvider):
        provider_name = "openai"
        supports_streaming = True
        supports_agentic_rag_planning = True

        def __init__(self) -> None:
            super().__init__()
            self.planner_calls = 0
            self.reflection_calls = 0

        async def generate_structured(self, prompt, schema, **kwargs):
            del prompt, kwargs
            if schema.__name__ == "_LLMRetrievalPlannerDecision":
                self.planner_calls += 1
                return schema(
                    queries=[
                        {
                            "query": "Agent 岗位薪资 学历 技能要求",
                            "purpose": "aggregation",
                        }
                    ],
                    preferred_channels=["lexical", "dense"],
                    confidence=0.95,
                )
            if schema.__name__ == "_LLMEvidenceReflectionDecision":
                self.reflection_calls += 1
                return schema(
                    status="repairable",
                    repair_actions=[
                        {
                            "action": "retrieve_statistics",
                            "query": "Agent 岗位薪资统计",
                            "target_dimension": "salary",
                        }
                    ],
                    confidence=0.95,
                )
            return schema()

    await _index(
        agentic_session,
        _job(
            "Agent 工程实习生",
            "负责 Agent 工具调用，要求熟悉 Python 和 RAG",
            company="Planning Lab",
            complete=False,
        ),
    )
    settings = Settings(rag_max_iterations=2, rag_max_queries=6)
    provider = PlanningProvider()
    pipeline = AgenticRAGPipeline(
        JobKnowledgeRAG(agentic_session, provider, settings),
        settings=settings,
        llm_provider=provider,
    )

    result = await pipeline.run(
        JobKnowledgeSearchRequest(query="分析 Agent 岗位的薪资、学历、经验、技能和工作职责")
    )

    assert provider.planner_calls == 1
    assert provider.reflection_calls == 1
    assert result.trace.agentic_capability_level == "full"
    assert result.trace.budget["calls_by_kind"]["planner"] == 1
    assert result.trace.budget["calls_by_kind"]["evidence_reflection"] == 1
    assert result.trace.budget["llm_calls_used"] == 2
    assert result.trace.planner_source == "llm"
    assert result.trace.reflection_iterations == 1
    assert "retrieve_statistics" in result.trace.repair_actions
    assert result.trace.stop_reason == "reflection_budget_exhausted"
    cached_plan, _, _ = await pipeline.llm_planner.plan(
        result.query_analysis,
        pipeline.planner.plan(result.query_analysis, JobKnowledgeFilters()),
        JobKnowledgeFilters(),
    )
    assert cached_plan is not None
    assert cached_plan.planner_source == "llm_cache"


@pytest.mark.asyncio
async def test_agentic_budget_counts_calls_before_execution_and_stops_repair(
    agentic_session: AsyncSession,
) -> None:
    await _index(
        agentic_session,
        _job(
            "Agent 工程实习生",
            "负责 Agent 工具调用，要求熟悉 Python",
            company="Budget Lab",
            complete=False,
        ),
    )
    settings = Settings(
        rag_max_iterations=2,
        rag_max_queries=6,
        rag_max_tool_calls=1,
        rag_max_search_calls=6,
    )
    pipeline = AgenticRAGPipeline(
        JobKnowledgeRAG(agentic_session, MockLLMProvider(), settings),
        settings=settings,
    )

    result = await pipeline.run(
        JobKnowledgeSearchRequest(query="分析 Agent 岗位的薪资、学历、经验、技能和工作职责")
    )

    assert result.trace.query_count == 1
    assert result.trace.budget["tool_calls_used"] == 1
    assert result.trace.budget["search_calls_used"] == 1
    assert result.trace.budget["exhausted"] is True
    assert result.trace.budget["exhausted_reason"] == "tool_call_budget_exhausted"
    assert result.trace.stop_reason == "tool_call_budget_exhausted"


@pytest.mark.asyncio
async def test_reranker_failure_uses_fusion_fallback(
    agentic_session: AsyncSession,
) -> None:
    await _index(
        agentic_session,
        _job("RAG 实习生", "负责 RAG 服务开发", company="Fallback Lab"),
    )
    pipeline = AgenticRAGPipeline(
        JobKnowledgeRAG(agentic_session, MockLLMProvider()),
        reranker=FailingReranker(),
    )

    result = await pipeline.run(JobKnowledgeSearchRequest(query="RAG 岗位技能"))

    assert result.search.citations
    assert any("Reranker 不可用" in item for item in result.trace.degradations)


@pytest.mark.asyncio
async def test_keyword_channel_failure_keeps_vector_retrieval_available(
    agentic_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _index(
        agentic_session,
        _job("Agent 实习生", "负责 Agent 和 RAG 服务开发", company="Vector Lab"),
    )
    rag = JobKnowledgeRAG(agentic_session, MockLLMProvider())
    original_search = rag.search

    async def search_with_failed_hybrid(request: JobKnowledgeSearchRequest):
        if request.retrieval_mode == "hybrid":
            raise RuntimeError("keyword channel unavailable")
        return await original_search(request)

    monkeypatch.setattr(rag, "search", search_with_failed_hybrid)
    result = await AgenticRAGPipeline(rag).run(
        JobKnowledgeSearchRequest(query="Agent RAG 岗位技能")
    )

    assert result.search.citations
    assert any("已降级为 vector 检索" in item for item in result.trace.degradations)


@pytest.mark.asyncio
async def test_empty_knowledge_base_and_agentic_api_are_explicitly_insufficient(
    agentic_session: AsyncSession,
    client: AsyncClient,
) -> None:
    result = await AgenticRAGPipeline(JobKnowledgeRAG(agentic_session, MockLLMProvider())).run(
        JobKnowledgeSearchRequest(query="量子计算岗位要求")
    )

    assert result.knowledge_status == "insufficient"
    assert result.confidence == "low"
    assert result.evidence == []
    assert result.evidence_evaluation.answerable is False

    response = await client.post(
        "/api/knowledge/agentic-search",
        json={"query": "量子计算岗位要求", "retrieval_mode": "hybrid"},
    )
    assert response.status_code == 200
    assert response.json()["knowledge_status"] == "insufficient"


@pytest.mark.asyncio
async def test_answer_verifier_uses_only_pipeline_sources(
    agentic_session: AsyncSession,
) -> None:
    await _index(
        agentic_session,
        _job("RAG 实习生", "负责 RAG 服务开发", company="Verify Lab"),
    )
    result = await AgenticRAGPipeline(JobKnowledgeRAG(agentic_session, MockLLMProvider())).run(
        JobKnowledgeSearchRequest(query="RAG 岗位需要哪些技能")
    )

    verification = AnswerVerifier().verify(
        "## 数据事实\n- 岗位要求 Python 和 RAG。\n\n## AI 建议\n建议完成检索项目。",
        result,
    )

    assert verification.citation_correctness == "valid"
    assert verification.groundedness in {"supported", "partially_supported"}
    assert verification.confidence in {"high", "medium"}

    internal_metric = f"{result.evidence_evaluation.coverage_score:.2f}"
    metric_verification = AnswerVerifier().verify(
        f"## 证据覆盖状态\n- 覆盖度：{internal_metric}\n\n## AI 建议\n继续验证。",
        result,
    )
    assert metric_verification.unsupported_claims == []
