from __future__ import annotations

from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm.provider import LLMProviderError, MockLLMProvider
from app.models.base import Base
from app.models.entities import BrowserTask, Job, JobSkill, Resume, ResumeChunk
from app.schemas.career_advisor import (
    CareerAdvisorAgentDecision,
    CareerAdvisorCancelApplicationRequest,
    CareerAdvisorConfirmApplicationRequest,
    CareerAdvisorMessageCreate,
    CareerAdvisorPrepareApplicationRequest,
    CareerAdvisorSessionCreate,
    CareerAdvisorToolPlan,
)
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.schemas.knowledge_search import JobKnowledgeFilters
from app.schemas.tool_protocol import (
    AgentToolCall,
    AgentToolResult,
    NativeToolResponse,
    TextContentBlock,
    ToolCallStatus,
    ToolDefinition,
    ToolSource,
)
from app.services.career_advisor import (
    CareerAdvisorService,
    CareerAdvisorToolService,
    classify_career_intent,
    clear_career_planner_cache,
)
from app.services.knowledge_indexing import KnowledgeIndexService


class FlakyStructuredProvider(MockLLMProvider):
    provider_name = "anthropic"
    model = "test-structured-model"

    def __init__(self) -> None:
        super().__init__()
        self.structured_attempts = 0

    async def generate_structured(
        self,
        prompt,
        schema,
        *,
        model=None,
        max_tokens=None,
        reasoning_effort=None,
    ):
        if schema is CareerAdvisorToolPlan:
            return schema(
                intent="skill_analysis",
                rewritten_query="AI Agent 技能要求",
                needs_knowledge=True,
                tool_names=["explain_skill_demand"],
                confidence=0.95,
                decision_summary="需要技能统计",
            )
        if schema is CareerAdvisorAgentDecision:
            if '"executed_tools": []' in prompt:
                return schema(
                    action="tool",
                    tool_name="explain_skill_demand",
                    query="AI Agent 技能要求",
                    decision_summary="先查询岗位技能证据",
                )
            return schema(action="answer", decision_summary="已有足够证据")
        self.structured_attempts += 1
        if self.structured_attempts == 1:
            raise LLMProviderError(
                "anthropic returned invalid structured output",
                retryable=True,
            )
        return schema(
            advice_markdown="优先完成一个可演示的 Agent 项目。",
            next_actions=["实现 RAG 检索", "补充自动化测试"],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["continue", "stop", "direct"])
async def test_react_observes_before_selecting_next_action(advisor_session, mode):
    clear_career_planner_cache()
    await _index_job(advisor_session)

    class ReActProvider(MockLLMProvider):
        provider_name = "anthropic"

        def __init__(self):
            super().__init__()
            self.observations = 0

        async def generate_structured(self, prompt, schema, **kwargs):
            if schema is CareerAdvisorToolPlan:
                return schema(
                    intent="general_career_chat",
                    normalized_question="解释 RAG 并说明岗位中的应用",
                    expanded_questions=["实际岗位要求哪些 RAG 能力"],
                    rewritten_query="RAG 岗位技能要求",
                    needs_knowledge=mode != "direct",
                    tool_names=[]
                    if mode == "direct"
                    else ["search_job_knowledge", "aggregate_job_market"],
                    confidence=0.95,
                    deep_dive=False,
                )
            if schema is CareerAdvisorAgentDecision:
                self.observations += 1
                assert "available_tools" in prompt
                if mode == "direct":
                    return schema(action="answer", decision_summary="直接回答")
                if self.observations == 1:
                    return schema(
                        action="tool",
                        tool_name="search_job_knowledge",
                        query="RAG 岗位技能要求",
                        decision_summary="先检索岗位证据",
                    )
                if mode == "continue" and self.observations == 2:
                    return schema(
                        action="tool",
                        tool_name="aggregate_job_market",
                        query="RAG 岗位技能要求",
                        decision_summary="再补充市场统计",
                    )
                return schema(action="answer", decision_summary="证据足够")
            return schema(advice_markdown="RAG 将检索证据用于生成回答。", next_actions=[])

    provider = ReActProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    conversation = await service.create_session(CareerAdvisorSessionCreate())
    answer = await service.send_message(
        conversation.id, CareerAdvisorMessageCreate(content="RAG 是什么？")
    )
    actual_tools = [item["tool"] for item in answer.tool_trace if "governance" in item]
    expected = [] if mode == "direct" else ["search_job_knowledge"]
    if mode == "continue":
        expected.append("aggregate_job_market")
    assert actual_tools == expected
    assert answer.status == "COMPLETED"
    assert answer.answer_metadata["normalized_question"] == "解释 RAG 并说明岗位中的应用"
    assert answer.answer_metadata["agent_architecture"] == "llamaindex_conversational_react_v2"
    assert any(item["tool"] == "llamaindex_react_workflow" for item in answer.tool_trace)


@pytest.mark.asyncio
async def test_conversational_agent_can_override_planner_suggestion(advisor_session) -> None:
    clear_career_planner_cache()
    await _index_job(advisor_session)

    class DynamicProvider(MockLLMProvider):
        provider_name = "anthropic"

        async def generate_structured(self, prompt, schema, **kwargs):
            if schema is CareerAdvisorToolPlan:
                return schema(
                    intent="market_research",
                    normalized_question="分析北京 RAG 岗位市场",
                    rewritten_query="北京 RAG 岗位",
                    needs_knowledge=True,
                    tool_names=["search_job_knowledge"],
                    confidence=0.96,
                )
            if schema is CareerAdvisorAgentDecision:
                if '"executed_tools": []' in prompt:
                    return schema(
                        action="tool",
                        tool_name="aggregate_job_market",
                        query="北京 RAG 岗位",
                        decision_summary="统计比普通检索更适合当前问题",
                    )
                return schema(action="answer", decision_summary="统计证据已足够")
            return schema(advice_markdown="北京 RAG 岗位需要工程与检索能力。")

    provider = DynamicProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    conversation = await service.create_session(CareerAdvisorSessionCreate())
    answer = await service.send_message(
        conversation.id,
        CareerAdvisorMessageCreate(content="北京 RAG 岗位市场怎么样？"),
    )

    actual_tools = [item["tool"] for item in answer.tool_trace if "governance" in item]
    assert actual_tools == ["aggregate_job_market"]
    assert answer.answer_metadata["suggested_tools"] == ["search_job_knowledge"]
    assert answer.answer_metadata["routing_mode"] == "model_driven"


@pytest.mark.asyncio
async def test_career_advisor_prefers_native_tool_calling_and_records_protocol(
    advisor_session,
) -> None:
    clear_career_planner_cache()
    await _index_job(advisor_session)

    class NativeProvider(MockLLMProvider):
        provider_name = "openai"
        model = "native-test"
        supports_native_tools = True

        def __init__(self):
            super().__init__()
            self.decisions = 0

        async def generate_structured(self, prompt, schema, **kwargs):
            if schema is CareerAdvisorToolPlan:
                return schema(
                    intent="market_research",
                    normalized_question="分析 RAG 岗位需求",
                    rewritten_query="RAG 岗位需求",
                    needs_knowledge=True,
                    tool_names=["search_job_knowledge"],
                    confidence=0.95,
                )
            return schema(advice_markdown="RAG 岗位需要检索、评估和工程能力。")

        async def decide_with_tools(self, prompt, tools, **kwargs):
            self.decisions += 1
            assert all(item.name in CAREER_ADVISOR_TOOL_MANIFESTS for item in tools)
            if self.decisions == 1:
                return NativeToolResponse(
                    provider="openai",
                    model=self.model,
                    stop_reason="tool_calls",
                    metadata={"protocol": "openai_chat_completions_tools"},
                    tool_calls=[
                        AgentToolCall(
                            call_id="call-1",
                            tool_name="search_job_knowledge",
                            arguments={"query": "RAG 岗位需求"},
                        )
                    ],
                )
            return NativeToolResponse(
                provider="openai",
                model=self.model,
                text="证据充分",
                stop_reason="stop",
                metadata={"protocol": "openai_chat_completions_tools"},
            )

    from app.services.tool_governance import CAREER_ADVISOR_TOOL_MANIFESTS

    provider = NativeProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    conversation = await service.create_session(CareerAdvisorSessionCreate())
    answer = await service.send_message(
        conversation.id,
        CareerAdvisorMessageCreate(content="RAG 岗位市场需要什么能力？"),
    )

    decisions = [item for item in answer.tool_trace if item["tool"] == "react_native_decision"]
    assert len(decisions) == 2
    assert decisions[0]["output"]["protocol"] == "openai_chat_completions_tools"
    assert decisions[0]["output"]["tool_calls"][0]["call_id"] == "call-1"
    assert not any(item["tool"] == "react_decision" for item in answer.tool_trace)


@pytest.mark.asyncio
async def test_career_advisor_can_select_an_enabled_read_only_mcp_tool(
    advisor_session,
) -> None:
    clear_career_planner_cache()
    external = ToolDefinition(
        name="mcp__market__lookup",
        description="External read-only market lookup",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        source=ToolSource.MCP,
        server_id="market",
        permissions=["external.read"],
        metadata={"remote_name": "lookup", "schema_hash": "c" * 64},
    )

    class NativeMCPProvider(MockLLMProvider):
        provider_name = "openai"
        supports_native_tools = True

        def __init__(self):
            super().__init__()
            self.decisions = 0

        async def generate_structured(self, prompt, schema, **kwargs):
            if schema is CareerAdvisorToolPlan:
                return schema(
                    intent="market_research",
                    normalized_question="外部岗位市场情况",
                    rewritten_query="外部岗位市场",
                    needs_knowledge=False,
                    tool_names=[],
                    confidence=0.9,
                )
            return schema(advice_markdown="已结合外部只读数据给出建议。")

        async def decide_with_tools(self, prompt, tools, **kwargs):
            self.decisions += 1
            assert external.name in {item.name for item in tools}
            if self.decisions == 1:
                return NativeToolResponse(
                    provider="openai",
                    stop_reason="tool_calls",
                    tool_calls=[
                        AgentToolCall(
                            call_id="mcp-call",
                            tool_name=external.name,
                            arguments={"query": "AI Agent"},
                        )
                    ],
                )
            assert "untrusted_external_data" in prompt
            return NativeToolResponse(provider="openai", stop_reason="stop", text="enough")

    provider = NativeMCPProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    service.mcp.advisor_definitions = AsyncMock(return_value=[external])
    service.mcp.call_advisor_tool = AsyncMock(
        return_value=AgentToolResult(
            call_id="mcp-call",
            tool_name=external.name,
            status=ToolCallStatus.SUCCESS,
            content=[TextContentBlock(text="AI Agent roles require Python and RAG")],
        )
    )
    conversation = await service.create_session(CareerAdvisorSessionCreate())

    answer = await service.send_message(
        conversation.id,
        CareerAdvisorMessageCreate(content="外部市场上的 AI Agent 岗位要求是什么？"),
    )

    assert answer.status == "COMPLETED"
    service.mcp.call_advisor_tool.assert_awaited_once()
    mcp_trace = next(item for item in answer.tool_trace if item["tool"] == external.name)
    assert mcp_trace["governance"]["permission_scopes"] == ["external.read"]
    assert mcp_trace["governance"]["untrusted_external_data"] is True


class LearningPlannerProvider(MockLLMProvider):
    provider_name = "anthropic"
    model = "test-planner-model"

    def __init__(self) -> None:
        super().__init__()
        self.planning_attempts = 0

    async def generate_structured(
        self,
        prompt,
        schema,
        *,
        model=None,
        max_tokens=None,
        reasoning_effort=None,
    ):
        if schema is CareerAdvisorToolPlan:
            self.planning_attempts += 1
            return schema(
                intent="learning_roadmap",
                rewritten_query="大模型应用开发学习路线",
                needs_knowledge=True,
                tool_names=["build_learning_roadmap"],
                confidence=0.94,
                decision_summary="需要岗位技能和学习路线",
            )
        if schema is CareerAdvisorAgentDecision:
            if '"executed_tools": []' in prompt:
                return schema(
                    action="tool",
                    tool_name="build_learning_roadmap",
                    query="大模型应用开发学习路线",
                    decision_summary="查询岗位需求并生成路线",
                )
            return schema(action="answer", decision_summary="路线证据已经足够")
        return schema(
            advice_markdown="根据岗位高频技能安排学习顺序。",
            next_actions=["完成一个大模型应用项目"],
        )


class FailingPlannerProvider(LearningPlannerProvider):
    async def generate_structured(
        self,
        prompt,
        schema,
        *,
        model=None,
        max_tokens=None,
        reasoning_effort=None,
    ):
        if schema is CareerAdvisorToolPlan:
            self.planning_attempts += 1
            raise LLMProviderError("planner unavailable", retryable=False)
        return await super().generate_structured(
            prompt,
            schema,
            model=model,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )


class DeepSeekAdviceProvider(LearningPlannerProvider):
    base_url = "https://api.deepseek.com/anthropic"
    supports_streaming = True

    def __init__(self) -> None:
        super().__init__()
        self.stream_attempts = 0

    async def stream(
        self,
        prompt,
        *,
        model=None,
        max_tokens=None,
        reasoning_effort=None,
    ):
        self.stream_attempts += 1
        assert max_tokens == 2200
        assert reasoning_effort == "none"
        assert "直接输出 Markdown 正文" in prompt
        yield "### 聚焦建议\n\n"
        yield "优先完成一个机器人控制闭环项目，并记录稳定性指标。"


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
    assert classify_career_intent("我想学大模型") == "learning_roadmap"
    assert classify_career_intent("大模型") == "skill_analysis"
    assert classify_career_intent("我想学Agent") == "learning_roadmap"


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
    assert "当前过滤条件" not in answer.content
    assert '"cities"' not in answer.content
    assert "代表性岗位引用" not in answer.content
    assert answer.answer_metadata["fact_source"] == "database"
    assert answer.answer_metadata["skill_deep_dive_count"] == 3
    assert answer.answer_metadata["skill_evidence_count"] > 0
    assert answer.answer_metadata["tool_governance"]["call_count"] >= 2
    assert answer.answer_metadata["tool_governance"]["rejected_count"] == 0
    assert answer.answer_metadata["tool_governance"]["verified_count"] >= 2
    assert "重点技能能力要求（JD 二次检索）" in answer.content
    assert "达标能力" in answer.content
    assert "项目证明" in answer.content
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
async def test_career_advisor_streams_facts_before_detailed_advice(
    advisor_session: AsyncSession,
) -> None:
    await _index_job(advisor_session)
    provider = MockLLMProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    session = await service.create_session(CareerAdvisorSessionCreate())
    pending = await service.create_pending_message(
        session.id,
        CareerAdvisorMessageCreate(content="我想学习 AI Agent，应该怎么准备？"),
    )
    events: list[tuple[str, dict]] = []

    async def capture(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    completed = await service.process_message(pending.id, capture)
    stages = [payload["stage"] for name, payload in events if name == "stage_changed"]
    streamed = "".join(str(payload["content"]) for name, payload in events if name == "delta")
    event_names = [name for name, _payload in events]

    assert stages == ["understanding", "searching", "analyzing", "writing", "finalizing"]
    assert "retrieval_status" in event_names
    assert "evidence_status" in event_names
    assert streamed == completed.content
    assert completed.answer_metadata["rag_mode"] == "agentic"
    assert completed.answer_metadata["rag_evidence_count"] >= 1
    assert "岗位技能需求拆解" in completed.content
    assert "重点技能能力要求（JD 二次检索）" in completed.content
    assert "学习顺序" in completed.content
    assert "12 周（0-90 天）学习顺序" in completed.content
    assert "作品集项目标准" in completed.content
    assert len(completed.content) > 1200


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
    assert "Python" in gap.content

    resume_search = await service.tools.search_job_knowledge(
        "AI Agent RAG",
        JobKnowledgeFilters(),
        resume_id=resume.id,
    )
    assert resume_search.resume_evidence

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
async def test_follow_up_reuses_previous_topic_for_retrieval(
    advisor_session: AsyncSession,
) -> None:
    job = await _index_job(advisor_session)
    provider = MockLLMProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    session = await service.create_session(CareerAdvisorSessionCreate())

    await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="我想学习 AI Agent，需要掌握哪些技术栈？"),
    )
    follow_up = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="还有其他建议吗？"),
    )

    assert follow_up.intent == "follow_up"
    assert follow_up.tool_trace[0]["input"]["query"] == "我想学习 AI Agent，需要掌握哪些技术栈？"
    assert follow_up.citations
    assert {citation.job_id for citation in follow_up.citations} == {job.id}
    detail = await service.get_session(session.id)
    assert "方向：我想学习 AI Agent" in detail.summary


@pytest.mark.asyncio
async def test_llm_planner_selects_tool_and_cache_reuses_decision(
    advisor_session: AsyncSession,
) -> None:
    clear_career_planner_cache()
    job = await _index_job(advisor_session)
    provider = LearningPlannerProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)

    first_session = await service.create_session(CareerAdvisorSessionCreate())
    first = await service.send_message(
        first_session.id,
        CareerAdvisorMessageCreate(content="我想学大模型"),
    )
    second_session = await service.create_session(CareerAdvisorSessionCreate())
    second = await service.send_message(
        second_session.id,
        CareerAdvisorMessageCreate(content="我想学大模型"),
    )

    assert first.intent == "learning_roadmap"
    assert first.answer_metadata["planner_source"] == "llm"
    assert first.answer_metadata["planned_tools"] == ["build_learning_roadmap"]
    assert first.answer_metadata["fact_source"] == "database"
    assert {citation.job_id for citation in first.citations} == {job.id}
    assert next(item for item in first.tool_trace if "governance" in item)["tool"] == (
        "build_learning_roadmap"
    )
    assert first.tool_trace[-1]["tool"] == "tool_planner"
    assert second.answer_metadata["planner_source"] == "llm_cache"
    assert second.answer_metadata["planned_tools"] == ["build_learning_roadmap"]
    assert provider.planning_attempts == 1


@pytest.mark.asyncio
async def test_llm_planner_failure_falls_back_to_knowledge_tool(
    advisor_session: AsyncSession,
) -> None:
    clear_career_planner_cache()
    await _index_job(advisor_session)
    provider = FailingPlannerProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    session = await service.create_session(CareerAdvisorSessionCreate())

    answer = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="我想学Agent"),
    )

    assert answer.status == "COMPLETED"
    assert answer.intent == "learning_roadmap"
    assert answer.answer_metadata["planner_source"] == "rules_fallback"
    assert answer.answer_metadata["planned_tools"] == ["build_learning_roadmap"]
    assert answer.answer_metadata["fact_source"] == "database"
    assert any("LLM 工具规划失败" in warning for warning in answer.answer_metadata["warnings"])
    assert next(item for item in answer.tool_trace if "governance" in item)["tool"] == (
        "build_learning_roadmap"
    )


@pytest.mark.asyncio
async def test_invalid_structured_advice_retries_once_before_fallback(
    advisor_session: AsyncSession,
) -> None:
    await _index_job(advisor_session)
    provider = FlakyStructuredProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    session = await service.create_session(CareerAdvisorSessionCreate())

    answer = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="AI Agent 岗位需要哪些技能？"),
    )

    assert provider.structured_attempts == 2
    assert answer.status == "COMPLETED"
    assert answer.answer_metadata["advice_source"] == "llm"
    assert "可演示的 Agent 项目" in answer.content
    assert not any(
        "invalid structured output" in warning for warning in answer.answer_metadata["warnings"]
    )


@pytest.mark.asyncio
async def test_deepseek_anthropic_advice_uses_plain_markdown_output(
    advisor_session: AsyncSession,
) -> None:
    await _index_job(advisor_session)
    provider = DeepSeekAdviceProvider()
    service = CareerAdvisorService(advisor_session, provider, embedding_provider=provider)
    session = await service.create_session(CareerAdvisorSessionCreate())
    pending = await service.create_pending_message(
        session.id,
        CareerAdvisorMessageCreate(content="给我一份 AI Agent 学习路线"),
    )
    events: list[tuple[str, dict]] = []

    async def capture(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    answer = await service.process_message(pending.id, capture)
    deltas = [str(payload["content"]) for event_type, payload in events if event_type == "delta"]

    assert provider.stream_attempts == 1
    assert "### 聚焦建议\n\n" in deltas
    assert "优先完成一个机器人控制闭环项目，并记录稳定性指标。" in deltas
    assert "".join(deltas) == answer.content
    assert answer.answer_metadata["advice_source"] == "llm"
    assert answer.answer_metadata["data_sufficient"] is False
    assert "给我一份 AI Agent 学习路线" in answer.content
    assert "大模型应用开发学习路线”方向" not in answer.content
    assert "机器人控制闭环项目" in answer.content


@pytest.mark.asyncio
async def test_pending_message_can_be_cancelled(
    advisor_session: AsyncSession,
) -> None:
    service = CareerAdvisorService(
        advisor_session,
        MockLLMProvider(),
        embedding_provider=MockLLMProvider(),
    )
    session = await service.create_session(CareerAdvisorSessionCreate())
    pending = await service.create_pending_message(
        session.id,
        CareerAdvisorMessageCreate(content="分析 AI Agent 岗位"),
    )

    cancelled = await service.cancel_message(pending.id)

    assert cancelled.status == "CANCELLED"
    assert cancelled.error_message == "用户已停止生成。"


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
    assert sessions.json()["items"][0]["messages"] == []

    session_detail = await client.get(f"/api/career-advisor/sessions/{session_id}")
    assert session_detail.status_code == 200
    assert session_detail.json()["messages"] == []

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

    paged = await client.get(f"/api/career-advisor/sessions/{session_id}?limit=2&offset=0")
    assert paged.status_code == 200
    assert len(paged.json()["messages"]) == 2
    assert paged.json()["message_total"] == 4
    assert paged.json()["message_offset"] == 0
    assert paged.json()["message_has_more"] is True

    citations = await client.get(f"/api/career-advisor/messages/{message.json()['id']}/citations")
    assert citations.status_code == 200
    assert citations.json()["total"] == 0

    regenerated = await client.post(
        f"/api/career-advisor/messages/{message.json()['id']}/regenerate/stream"
    )
    assert regenerated.status_code == 200
    assert "message_started" in regenerated.text
    assert "message_state" in regenerated.text

    final_detail = await client.get(f"/api/career-advisor/sessions/{session_id}")
    assert final_detail.status_code == 200
    assert len(final_detail.json()["messages"]) == 6


@pytest.mark.asyncio
async def test_career_advisor_session_crud_and_list_pagination(
    client: AsyncClient,
) -> None:
    created_ids: list[str] = []
    for index in range(3):
        created = await client.post(
            "/api/career-advisor/sessions",
            json={"title": f"咨询 {index + 1}"},
        )
        assert created.status_code == 201
        created_ids.append(created.json()["id"])

    first_page = await client.get("/api/career-advisor/sessions?limit=2&offset=0")
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert first_page.json()["limit"] == 2
    assert first_page.json()["offset"] == 0
    assert first_page.json()["has_more"] is True
    assert len(first_page.json()["items"]) == 2
    assert all(item["messages"] == [] for item in first_page.json()["items"])

    second_page = await client.get("/api/career-advisor/sessions?limit=2&offset=2")
    assert second_page.status_code == 200
    assert second_page.json()["has_more"] is False
    assert len(second_page.json()["items"]) == 1

    renamed = await client.patch(
        f"/api/career-advisor/sessions/{created_ids[0]}",
        json={"title": "新的咨询名称"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "新的咨询名称"

    deleted = await client.delete(f"/api/career-advisor/sessions/{created_ids[0]}")
    assert deleted.status_code == 204
    missing = await client.get(f"/api/career-advisor/sessions/{created_ids[0]}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_career_advisor_job_card_requires_confirmation_and_is_idempotent(
    advisor_session: AsyncSession,
) -> None:
    job = _job()
    job.platform = "mock"
    advisor_session.add(job)
    await advisor_session.commit()
    service = CareerAdvisorService(advisor_session, MockLLMProvider())
    user = await service._default_user()
    resume = Resume(
        user_id=user.id,
        name="卡片测试简历",
        raw_text="Python RAG",
        structured_profile={"skills": ["Python", "RAG"]},
    )
    advisor_session.add(resume)
    await advisor_session.commit()
    session = await service.create_session(CareerAdvisorSessionCreate(resume_id=resume.id))

    answer = await service.send_message(
        session.id,
        CareerAdvisorMessageCreate(content="帮我找北京 AI Agent 实习岗位"),
    )
    action = answer.answer_metadata["ui_action"]
    assert action["type"] == "job_search_results"
    assert action["default_selected_job_ids"] == [str(job.id)]

    prepared = await service.prepare_application(
        session.id,
        CareerAdvisorPrepareApplicationRequest(
            message_id=answer.id,
            job_ids=[job.id],
            resume_id=resume.id,
        ),
    )
    confirmation = prepared["ui_action"]
    assert confirmation["type"] == "application_confirmation"
    assert confirmation["campaign_id"]
    assert not (await advisor_session.scalars(select(BrowserTask))).all()

    cancelled_draft = await service.cancel_application(
        session.id,
        CareerAdvisorCancelApplicationRequest(
            message_id=answer.id,
            campaign_id=confirmation["campaign_id"],
        ),
    )
    assert cancelled_draft["ui_action"]["status"] == "cancelled"
    prepared = await service.prepare_application(
        session.id,
        CareerAdvisorPrepareApplicationRequest(
            message_id=answer.id,
            job_ids=[job.id],
            resume_id=resume.id,
        ),
    )
    confirmation = prepared["ui_action"]

    confirmed = await service.confirm_application(
        session.id,
        CareerAdvisorConfirmApplicationRequest(
            message_id=answer.id,
            campaign_id=confirmation["campaign_id"],
            confirmation_token=confirmation["confirmation_token"],
        ),
    )
    assert confirmed["ui_action"]["type"] == "application_progress"
    assert len(confirmed["ui_action"]["items"]) == 1
    repeated = await service.confirm_application(
        session.id,
        CareerAdvisorConfirmApplicationRequest(
            message_id=answer.id,
            campaign_id=confirmation["campaign_id"],
            confirmation_token=confirmation["confirmation_token"],
        ),
    )
    assert len(repeated["ui_action"]["items"]) == 1
    with pytest.raises(Exception, match="无效"):
        await service.confirm_application(
            session.id,
            CareerAdvisorConfirmApplicationRequest(
                message_id=answer.id,
                campaign_id=confirmation["campaign_id"],
                confirmation_token=confirmation["confirmation_token"] + "x",
            ),
        )
