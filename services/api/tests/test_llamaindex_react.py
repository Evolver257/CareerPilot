from __future__ import annotations

import pytest

from app.services.llamaindex_react import (
    CareerAdvisorReActWorkflow,
    ReActDecision,
)


@pytest.mark.asyncio
async def test_agent_can_answer_immediately_without_following_fallback_plan() -> None:
    calls: list[str] = []

    async def execute(tool_name: str, _arguments: dict) -> None:
        calls.append(tool_name)

    async def decide(*_args) -> ReActDecision:
        return ReActDecision(action="answer", decision_summary="普通交流可直接回答")

    result = await CareerAdvisorReActWorkflow(
        available_tools=["search", "market"],
        fallback_tools=["search"],
        required_tools=[],
        execute_tool=execute,
        decide_action=decide,
    ).run()

    assert calls == []
    assert result.stop_reason == "agent_answer"
    assert result.iterations == 0


@pytest.mark.asyncio
async def test_agent_can_choose_tool_outside_suggested_route() -> None:
    calls: list[tuple[str, dict]] = []

    async def execute(tool_name: str, arguments: dict) -> None:
        calls.append((tool_name, arguments))

    async def decide(_last, executed, _iteration) -> ReActDecision:
        if not executed:
            return ReActDecision(
                action="tool",
                tool_name="market",
                arguments={"query": "北京 RAG 实习"},
                decision_summary="需要市场统计",
            )
        return ReActDecision(action="answer", decision_summary="证据已经足够")

    result = await CareerAdvisorReActWorkflow(
        available_tools=["search", "market"],
        fallback_tools=["search"],
        required_tools=[],
        execute_tool=execute,
        decide_action=decide,
    ).run()

    assert calls == [("market", {"query": "北京 RAG 实习"})]
    assert result.executed_tools == ("market",)
    assert result.stop_reason == "agent_answer"


@pytest.mark.asyncio
async def test_agent_cannot_skip_policy_required_tool() -> None:
    calls: list[str] = []

    async def execute(tool_name: str, _arguments: dict) -> None:
        calls.append(tool_name)

    async def decide(*_args) -> ReActDecision:
        return ReActDecision(action="answer", decision_summary="尝试提前回答")

    result = await CareerAdvisorReActWorkflow(
        available_tools=["search", "resume_gap"],
        fallback_tools=[],
        required_tools=["resume_gap"],
        execute_tool=execute,
        decide_action=decide,
    ).run()

    assert calls == ["resume_gap"]
    assert result.executed_tools == ("resume_gap",)
    assert result.stop_reason == "agent_answer"


@pytest.mark.asyncio
async def test_agent_uses_safe_fallback_only_when_decision_is_unavailable() -> None:
    calls: list[str] = []

    async def execute(tool_name: str, _arguments: dict) -> None:
        calls.append(tool_name)

    async def decide(*_args) -> None:
        return None

    result = await CareerAdvisorReActWorkflow(
        available_tools=["search", "market"],
        fallback_tools=["search", "market"],
        required_tools=[],
        execute_tool=execute,
        decide_action=decide,
    ).run()

    assert calls == ["search", "market"]
    assert result.executed_tools == ("search", "market")
    assert result.stop_reason == "fallback_exhausted"


@pytest.mark.asyncio
async def test_agent_completes_required_capability_before_answering() -> None:
    calls: list[str] = []

    async def execute(tool_name: str, _arguments: dict) -> None:
        calls.append(tool_name)

    async def decide(*_args) -> ReActDecision:
        return ReActDecision(action="answer", decision_summary="尝试提前回答")

    result = await CareerAdvisorReActWorkflow(
        available_tools=["search_job_knowledge", "explain_skill_demand"],
        fallback_tools=[],
        required_tools=[],
        required_capabilities={
            "market_demand_evidence": (
                "explain_skill_demand",
                "search_job_knowledge",
            )
        },
        execute_tool=execute,
        decide_action=decide,
    ).run()

    assert calls == ["explain_skill_demand"]
    assert result.executed_tools == ("explain_skill_demand",)
    assert result.stop_reason == "agent_answer"
