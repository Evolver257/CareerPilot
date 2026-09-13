from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from llama_index.core.workflow import Event, StartEvent, StopEvent, Workflow, step


@dataclass(frozen=True)
class ReActDecision:
    """One model-selected action without exposing private chain-of-thought."""

    action: Literal["answer", "tool"]
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    decision_summary: str = ""


@dataclass(frozen=True)
class ReActWorkflowResult:
    executed_tools: tuple[str, ...]
    iterations: int
    stop_reason: str
    decision_summary: str = ""


ExecuteTool = Callable[[str, dict[str, Any]], Awaitable[None]]
DecideAction = Callable[
    [str | None, tuple[str, ...], int], Awaitable[ReActDecision | None]
]


class _DecisionEvent(Event):
    last_tool: str | None = None
    executed: list[str]
    iterations: int = 0


class _ActionEvent(Event):
    tool_name: str
    arguments: dict[str, Any]
    executed: list[str]
    iterations: int
    decision_summary: str = ""


def _unique_tools(names: Sequence[str], *, excluding: Sequence[str] = ()) -> list[str]:
    excluded = set(excluding)
    result: list[str] = []
    for name in names:
        if name and name not in excluded and name not in result:
            result.append(name)
    return result


class CareerAdvisorReActWorkflow(Workflow):
    """Conversation-driven, bounded ReAct loop built with LlamaIndex Workflow.

    No business route is encoded in this workflow. At every decision point the
    model may answer or choose any currently exposed tool. Suggested tools are
    used only when the decision model is unavailable; required tools are policy
    constraints such as an explicitly requested resume comparison.
    """

    def __init__(
        self,
        *,
        available_tools: Sequence[str],
        fallback_tools: Sequence[str],
        required_tools: Sequence[str],
        required_capabilities: Mapping[str, Sequence[str]] | None = None,
        execute_tool: ExecuteTool,
        decide_action: DecideAction,
        max_iterations: int = 5,
    ) -> None:
        super().__init__(timeout=None, verbose=False)
        self._available_tools = set(_unique_tools(available_tools))
        self._fallback_tools = _unique_tools(fallback_tools)
        self._required_tools = _unique_tools(required_tools)
        self._required_capabilities = {
            capability: tuple(
                name
                for name in _unique_tools(tool_names)
                if name in self._available_tools
            )
            for capability, tool_names in (required_capabilities or {}).items()
            if capability and _unique_tools(tool_names)
        }
        self._execute_tool = execute_tool
        self._decide_action = decide_action
        self._max_iterations = max(1, max_iterations)

    @staticmethod
    def _result(
        event: _DecisionEvent | _ActionEvent,
        reason: str,
        summary: str = "",
    ) -> StopEvent:
        return StopEvent(
            result=ReActWorkflowResult(
                executed_tools=tuple(event.executed),
                iterations=event.iterations,
                stop_reason=reason,
                decision_summary=summary,
            )
        )

    def _fallback_action(self, executed: Sequence[str]) -> str | None:
        missing_capabilities = self._missing_capabilities(executed)
        capability_tools = [
            tool_name
            for capability, tool_names in self._required_capabilities.items()
            if capability in missing_capabilities
            for tool_name in tool_names
        ]
        pending = _unique_tools(
            [*self._required_tools, *capability_tools, *self._fallback_tools],
            excluding=executed,
        )
        return pending[0] if pending else None

    def _missing_capabilities(self, executed: Sequence[str]) -> tuple[str, ...]:
        executed_set = set(executed)
        return tuple(
            capability
            for capability, tool_names in self._required_capabilities.items()
            if not executed_set.intersection(tool_names)
        )

    @step
    async def start(self, event: StartEvent) -> _DecisionEvent:
        del event
        return _DecisionEvent(executed=[])

    @step
    async def decide(self, event: _DecisionEvent) -> _ActionEvent | StopEvent:
        if event.iterations >= self._max_iterations:
            return self._result(event, "max_iterations")

        decision = await self._decide_action(
            event.last_tool,
            tuple(event.executed),
            event.iterations,
        )
        missing_required = _unique_tools(self._required_tools, excluding=event.executed)
        missing_capabilities = self._missing_capabilities(event.executed)
        if (
            decision is not None
            and decision.action == "answer"
            and not missing_required
            and not missing_capabilities
        ):
            return self._result(event, "agent_answer", decision.decision_summary)

        if (
            decision is not None
            and decision.action == "tool"
            and decision.tool_name in self._available_tools
            and decision.tool_name not in event.executed
        ):
            return _ActionEvent(
                tool_name=decision.tool_name,
                arguments=dict(decision.arguments),
                executed=list(event.executed),
                iterations=event.iterations,
                decision_summary=decision.decision_summary,
            )

        fallback_tool = self._fallback_action(event.executed)
        if fallback_tool is None:
            reason = "agent_answer" if decision is not None else "fallback_exhausted"
            summary = decision.decision_summary if decision is not None else ""
            return self._result(event, reason, summary)
        return _ActionEvent(
            tool_name=fallback_tool,
            arguments={},
            executed=list(event.executed),
            iterations=event.iterations,
            decision_summary=(
                "补齐必需能力：" + "、".join(missing_capabilities)
                if missing_capabilities
                else "使用安全兜底动作"
            ),
        )

    @step
    async def act(self, event: _ActionEvent) -> _DecisionEvent:
        await self._execute_tool(event.tool_name, event.arguments)
        return _DecisionEvent(
            last_tool=event.tool_name,
            executed=[*event.executed, event.tool_name],
            iterations=event.iterations + 1,
        )
