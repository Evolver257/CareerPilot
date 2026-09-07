from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.models.entities import AgentEvent, AgentRun, AgentStep, AgentToolInvocation
from app.models.states import AgentEventType, AgentRunStatus, AgentStepStatus
from app.repositories.agents import AgentRepository
from app.repositories.matching import MatchingRepository
from app.schemas.agents import AgentRunCreate, AgentRunResumeRequest, AgentRunUpdate
from app.schemas.tool_protocol import RetryPolicy
from app.services.agent_reliability import (
    classify_tool_error,
    retry_delay_ms,
    should_retry,
)
from app.services.agent_tools import AgentTool, AgentToolService, ToolRegistry
from app.services.tool_governance import (
    CapabilityMatcher,
    GoalValidator,
    GovernancePhase,
    RecoveryAction,
    ToolBudget,
    ToolCallHistory,
    ToolCallValidator,
    ToolCritic,
    ToolExecutionResult,
    ToolExposureManager,
    ToolNeedClassifier,
    ToolRecoveryManager,
    ToolResultVerifier,
)
from app.services.tool_protocol import canonical_tool_signature
from app.services.work_queue import enqueue_work


class AgentRunNotFoundError(ValueError):
    """Raised when an Agent Run does not exist."""


class AgentRunActionError(ValueError):
    """Raised when an Agent Run action is invalid for its current state."""


class AgentExecutionError(RuntimeError):
    """Raised when execution cannot continue safely."""


class AgentReplanRequested(AgentExecutionError):
    """Raised internally after a failed result has produced a new safe plan."""


@dataclass
class AgentState:
    plan: list[str]
    criteria: dict[str, Any]
    next_step: int = 0
    step_sequence: int = 0
    selected_job_ids: list[str] = field(default_factory=list)
    phase: str = GovernancePhase.UNDERSTAND.value
    required_capabilities: list[str] = field(default_factory=list)
    need_tool: bool = True
    need_tool_reason: str = ""
    need_tool_confidence: float = 1.0
    tool_call_count: int = 0
    call_history: list[dict[str, Any]] = field(default_factory=list)
    approval_granted: bool = False
    last_governance_trace: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, value: dict[str, Any]) -> AgentState:
        return cls(
            plan=list(value.get("plan", [])),
            criteria=dict(value.get("criteria", {})),
            next_step=int(value.get("next_step", 0)),
            step_sequence=int(value.get("step_sequence", 0)),
            selected_job_ids=list(value.get("selected_job_ids", [])),
            phase=str(value.get("phase", GovernancePhase.UNDERSTAND.value)),
            required_capabilities=list(value.get("required_capabilities", [])),
            need_tool=bool(value.get("need_tool", True)),
            need_tool_reason=str(value.get("need_tool_reason", "")),
            need_tool_confidence=float(value.get("need_tool_confidence", 1.0)),
            tool_call_count=int(value.get("tool_call_count", 0)),
            call_history=list(value.get("call_history", [])),
            approval_granted=bool(value.get("approval_granted", False)),
            last_governance_trace=dict(value.get("last_governance_trace", {})),
        )

    def dump(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "criteria": self.criteria,
            "next_step": self.next_step,
            "step_sequence": self.step_sequence,
            "selected_job_ids": self.selected_job_ids,
            "phase": self.phase,
            "required_capabilities": self.required_capabilities,
            "need_tool": self.need_tool,
            "need_tool_reason": self.need_tool_reason,
            "need_tool_confidence": self.need_tool_confidence,
            "tool_call_count": self.tool_call_count,
            "call_history": self.call_history,
            "approval_granted": self.approval_granted,
            "last_governance_trace": self.last_governance_trace,
        }


class AgentMemory:
    @staticmethod
    def initialize(*, goal: str, resume_id: UUID) -> dict[str, Any]:
        return {
            "working": {"goal": goal, "tool_results": {}},
            "session": {"resume_id": str(resume_id), "campaign_id": None},
            "governance": {"traces": [], "last_result": None},
        }

    @staticmethod
    def record(memory: dict[str, Any], tool_name: str, output: dict[str, Any]) -> dict[str, Any]:
        updated = {key: value for key, value in memory.items()}
        updated["working"] = dict(memory.get("working", {}))
        updated["session"] = dict(memory.get("session", {}))
        results = dict(updated["working"].get("tool_results", {}))
        results[tool_name] = output
        updated["working"]["tool_results"] = results
        if tool_name == "create_campaign":
            updated["session"]["campaign_id"] = output.get("campaign_id")
        return updated

    @staticmethod
    def record_governance(memory: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
        updated = {key: value for key, value in memory.items()}
        governance = dict(memory.get("governance", {}))
        traces = list(governance.get("traces", []))
        traces.append(trace)
        governance["traces"] = traces[-100:]
        governance["last_result"] = trace.get("result_verification")
        updated["governance"] = governance
        return updated

    @staticmethod
    def result(memory: dict[str, Any], tool_name: str) -> dict[str, Any]:
        working = memory.get("working", {})
        return dict(working.get("tool_results", {}).get(tool_name, {}))


class AgentPlanner:
    plan = [
        "search_jobs",
        "analyze_job",
        "retrieve_resume",
        "rank_jobs",
        "create_campaign",
        "request_approval",
    ]

    def create_state(self, goal: str) -> AgentState:
        decision = ToolNeedClassifier().classify(goal)
        return AgentState(
            plan=list(self.plan),
            criteria=self._criteria(goal),
            required_capabilities=list(decision.required_capabilities),
            need_tool=decision.need_tool,
            need_tool_reason=decision.reason,
            need_tool_confidence=decision.confidence,
        )

    @staticmethod
    def _criteria(goal: str) -> dict[str, Any]:
        score_match = re.search(
            r"(?:匹配度|分数|score)\s*[:：]?\s*(\d{1,3})\s*分?\s*(?:以上|起)?"
            r"|(\d{1,3})\s*分\s*(?:以上|起)",
            goal,
            re.I,
        )
        matched_score = (
            next((group for group in score_match.groups() if group is not None), None)
            if score_match
            else None
        )
        min_score = min(100.0, float(matched_score)) if matched_score else 70.0
        count_match = re.search(r"(?:最多|前|Top)\s*(\d{1,3})\s*(?:个|条)?", goal, re.I)
        max_jobs = min(100, int(count_match.group(1))) if count_match else 10
        cities = [
            city
            for city in ["北京", "上海", "深圳", "杭州", "广州", "Remote", "远程"]
            if city.casefold() in goal.casefold()
        ]
        keywords: list[str] = []
        for keyword in [
            "AI Agent",
            "LLM",
            "RAG",
            "Backend",
            "Frontend",
            "Engineer",
            "Data",
            "DevOps",
            "实习",
        ]:
            if keyword.casefold() in goal.casefold():
                keywords.append(keyword)
        if not keywords:
            stop_words = {"help", "find", "jobs", "job", "score", "top"}
            keywords = [
                token
                for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]+", goal)
                if token.casefold() not in stop_words
            ][:10]
        return {
            "keywords": list(dict.fromkeys(keywords)),
            "cities": list(dict.fromkeys(cities)),
            "min_score": min_score,
            "max_jobs": max_jobs,
        }


class AgentEventEmitter:
    def __init__(self, repository: AgentRepository) -> None:
        self.repository = repository

    def emit(
        self,
        run: AgentRun,
        event_type: AgentEventType,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.repository.add_event(
            AgentEvent(
                run_id=run.id,
                event_type=event_type.value,
                payload=payload or {},
            )
        )


class AgentExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute(self, tool_name: str, payload: dict[str, Any]) -> ToolExecutionResult:
        started = perf_counter()
        try:
            output = await self.registry.get(tool_name).execute(payload)
            return ToolExecutionResult(
                execution_status="SUCCESS",
                semantic_status="UNKNOWN",
                data=output,
                latency_ms=round((perf_counter() - started) * 1000, 2),
            )
        except TimeoutError as exc:
            return ToolExecutionResult(
                execution_status="TIMEOUT",
                semantic_status="UNKNOWN",
                error=str(exc) or "tool timed out",
                latency_ms=round((perf_counter() - started) * 1000, 2),
            )
        except Exception as exc:
            return ToolExecutionResult(
                execution_status="FAILED",
                semantic_status="UNKNOWN",
                error=str(exc),
                latency_ms=round((perf_counter() - started) * 1000, 2),
            )


class AgentRuntime:
    terminal = {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.FAILED,
        AgentRunStatus.TIMED_OUT,
    }

    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        settings: Settings | None = None,
        embedding_provider: LLMProvider | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.embedding_provider = embedding_provider or provider
        self.settings = settings or get_settings()
        self.repository = AgentRepository(session)
        self.registry: ToolRegistry = AgentToolService(
            session,
            provider,
            self.settings,
            embedding_provider=self.embedding_provider,
        ).registry()
        self.executor = AgentExecutor(self.registry)
        self.planner = AgentPlanner()
        self.events = AgentEventEmitter(self.repository)
        self.exposure = ToolExposureManager()
        self.matcher = CapabilityMatcher()
        self.call_validator = ToolCallValidator()
        self.result_verifier = ToolResultVerifier()
        self.goal_validator = GoalValidator()
        self.recovery = ToolRecoveryManager()
        self.critic = ToolCritic()
        self.input_builders = {
            "search_jobs": self._search_input,
            "analyze_job": self._analyze_input,
            "retrieve_resume": self._resume_input,
            "score_job": self._score_input,
            "rank_jobs": self._rank_input,
            "create_campaign": self._campaign_input,
            "request_approval": self._approval_input,
            "queue_application": self._queue_input,
        }

    async def list_runs(self) -> tuple[list[AgentRun], int]:
        return await self.repository.list_runs()

    async def get_run(self, run_id: UUID) -> AgentRun:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise AgentRunNotFoundError("Agent Run not found")
        return run

    async def create(self, payload: AgentRunCreate) -> AgentRun:
        matching = MatchingRepository(self.session)
        resume = (
            await matching.get_resume(payload.resume_id)
            if payload.resume_id
            else await matching.get_default_resume()
        )
        if resume is None:
            raise AgentRunActionError("Upload or select a resume before running the agent")
        state = self.planner.create_state(payload.goal)
        run = AgentRun(
            id=uuid4(),
            user_id=resume.user_id,
            agent_type="job_search_orchestrator",
            status=AgentRunStatus.PENDING.value,
            run_input={
                "goal": payload.goal,
                "resume_id": str(resume.id),
                "background": payload.background,
            },
            run_output={},
            agent_state=state.dump(),
            memory=AgentMemory.initialize(goal=payload.goal, resume_id=resume.id),
            max_steps=payload.max_steps,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )
        self.events.emit(run, AgentEventType.RUN_CREATED, {"goal": payload.goal})
        run = await self.repository.checkpoint(run)
        if not payload.auto_start:
            return run
        if payload.background:
            return await self.enqueue_background(run.id)
        return await self.start(run.id)

    async def enqueue_background(self, run_id: UUID, *, retry: bool = False) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status != AgentRunStatus.PENDING.value:
            raise AgentRunActionError(f"Agent Run cannot be queued from {run.status}")
        run.run_input = {**run.run_input, "background": True}
        await enqueue_work(self.session, "agent", run.id, retry=retry)
        return await self.repository.checkpoint(run)

    async def run_background(self, run_id: UUID) -> AgentRun:
        """Start or resume a checkpointed run after worker/process interruption."""

        run = await self.get_run(run_id)
        if run.status == AgentRunStatus.PENDING.value:
            return await self.start(run_id)
        if run.status == AgentRunStatus.RUNNING.value:
            return await self._run_until_blocked(run)
        return run

    async def update(self, run_id: UUID, payload: AgentRunUpdate) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status != AgentRunStatus.PENDING.value:
            raise AgentRunActionError("Only pending Agent Runs can be edited")
        if payload.goal is not None:
            run.run_input = {**run.run_input, "goal": payload.goal}
            run.agent_state = self.planner.create_state(payload.goal).dump()
            resume_id = UUID(str(run.run_input["resume_id"]))
            run.memory = AgentMemory.initialize(goal=payload.goal, resume_id=resume_id)
        for setting_name in ("max_steps", "timeout_seconds", "max_retries"):
            value = getattr(payload, setting_name)
            if value is not None:
                setattr(run, setting_name, value)
        return await self.repository.checkpoint(run)

    async def delete(self, run_id: UUID) -> None:
        run = await self.get_run(run_id)
        deletable = {status.value for status in self.terminal} | {AgentRunStatus.PENDING.value}
        if run.status not in deletable:
            raise AgentRunActionError(
                "Running or waiting Agent Runs must be cancelled before deletion"
            )
        await self.session.delete(run)
        await self.session.commit()

    async def start(self, run_id: UUID) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status != AgentRunStatus.PENDING.value:
            raise AgentRunActionError(f"Agent Run cannot start from {run.status}")
        run.status = AgentRunStatus.RUNNING.value
        run.started_at = datetime.now(UTC)
        self.events.emit(run, AgentEventType.RUN_STARTED)
        run = await self.repository.checkpoint(run)
        return await self._run_until_blocked(run)

    async def pause(self, run_id: UUID) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status not in {AgentRunStatus.PENDING.value, AgentRunStatus.RUNNING.value}:
            raise AgentRunActionError(f"Agent Run cannot pause from {run.status}")
        run.status_before_pause = run.status
        run.status = AgentRunStatus.PAUSED.value
        self.events.emit(run, AgentEventType.RUN_PAUSED)
        return await self.repository.checkpoint(run)

    async def resume(self, run_id: UUID, payload: AgentRunResumeRequest) -> AgentRun:
        run = await self.get_run(run_id)
        if run.status == AgentRunStatus.PAUSED.value:
            run.status = AgentRunStatus.RUNNING.value
            run.status_before_pause = None
            if run.started_at is None:
                run.started_at = datetime.now(UTC)
            self.events.emit(run, AgentEventType.RUN_RESUMED, {"reason": "pause"})
            run = await self.repository.checkpoint(run)
            return await self._run_until_blocked(run)
        if run.status != AgentRunStatus.WAITING_FOR_USER.value:
            raise AgentRunActionError(f"Agent Run cannot resume from {run.status}")
        if payload.approved is None:
            raise AgentRunActionError("Approval decision is required")
        if not payload.approved:
            run.status = AgentRunStatus.COMPLETED.value
            run.finished_at = datetime.now(UTC)
            run.run_output = {
                **run.run_output,
                "approved": False,
                "message": "User rejected the candidate applications.",
            }
            self.events.emit(run, AgentEventType.RUN_COMPLETED, {"approved": False})
            return await self.repository.checkpoint(run)
        state = AgentState.load(run.agent_state)
        campaign_result = AgentMemory.result(run.memory, "create_campaign")
        available = [item["job_id"] for item in campaign_result.get("candidates", [])]
        selected = [str(job_id) for job_id in payload.selected_job_ids] or available
        if not selected:
            run.status = AgentRunStatus.COMPLETED.value
            run.finished_at = datetime.now(UTC)
            run.run_output = {**run.run_output, "approved": True, "queued_count": 0}
            self.events.emit(run, AgentEventType.RUN_COMPLETED, {"queued_count": 0})
            return await self.repository.checkpoint(run)
        invalid = [job_id for job_id in selected if job_id not in available]
        if invalid:
            raise AgentRunActionError("Selected jobs are not in the approval candidate list")
        state.selected_job_ids = selected
        state.approval_granted = True
        if "queue_application" not in state.plan:
            state.plan.append("queue_application")
        run.agent_state = state.dump()
        run.status = AgentRunStatus.RUNNING.value
        self.events.emit(run, AgentEventType.RUN_RESUMED, {"reason": "approval"})
        run = await self.repository.checkpoint(run)
        return await self._run_until_blocked(run)

    async def cancel(self, run_id: UUID) -> AgentRun:
        run = await self.get_run(run_id)
        if AgentRunStatus(run.status) in self.terminal:
            raise AgentRunActionError(f"Agent Run cannot cancel from {run.status}")
        run.status = AgentRunStatus.CANCELLED.value
        run.finished_at = datetime.now(UTC)
        self.events.emit(run, AgentEventType.RUN_CANCELLED)
        return await self.repository.checkpoint(run)

    async def retry(self, run_id: UUID) -> AgentRun:
        """Start a fresh auditable run after a terminal execution failure."""

        source = await self.get_run(run_id)
        if source.status not in {
            AgentRunStatus.FAILED.value,
            AgentRunStatus.TIMED_OUT.value,
        }:
            raise AgentRunActionError(f"Agent Run cannot retry from {source.status}")
        resume_id = source.run_input.get("resume_id")
        if not resume_id:
            raise AgentRunActionError("Agent Run cannot retry without its resume")
        retried = await self.create(
            AgentRunCreate(
                goal=str(source.run_input.get("goal", "Retry Agent Run")),
                resume_id=UUID(str(resume_id)),
                auto_start=False,
                max_steps=source.max_steps,
                timeout_seconds=source.timeout_seconds,
                max_retries=source.max_retries,
                background=bool(source.run_input.get("background", False)),
            )
        )
        retried.run_input = {
            **retried.run_input,
            "retry_of": str(source.id),
            "retry_reason": source.error,
        }
        retried = await self.repository.checkpoint(retried)
        if retried.run_input.get("background"):
            return await self.enqueue_background(retried.id, retry=True)
        return await self.start(retried.id)

    async def _run_until_blocked(self, run: AgentRun) -> AgentRun:
        run_id = run.id
        elapsed = 0.0
        if run.started_at is not None:
            started_at = run.started_at
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            elapsed = max(0.0, (datetime.now(UTC) - started_at).total_seconds())
        deadline = perf_counter() + max(0.0, run.timeout_seconds - elapsed)
        try:
            while run.status == AgentRunStatus.RUNNING.value:
                state = AgentState.load(run.agent_state)
                if state.next_step >= len(state.plan):
                    return await self._complete(run)
                if state.step_sequence >= run.max_steps:
                    raise AgentExecutionError("Agent reached max_steps")
                remaining = deadline - perf_counter()
                if remaining <= 0:
                    return await self._timeout(run.id)
                tool_name = state.plan[state.next_step]
                tool = self.registry.get(tool_name)
                state.phase = self._phase_for_tool(tool_name).value
                tool_input = self.input_builders[tool_name](run, state)
                try:
                    output, run, state = await self._execute_with_retry(
                        run,
                        state,
                        tool,
                        tool_input,
                        remaining,
                    )
                except AgentReplanRequested:
                    run = await self.get_run(run.id)
                    continue
                run.memory = AgentMemory.record(run.memory, tool_name, output)
                if tool_name == "create_campaign":
                    run.campaign_id = UUID(output["campaign_id"])
                state.next_step += 1
                run.agent_state = state.dump()
                if output.get("user_action_required"):
                    run.status = AgentRunStatus.WAITING_FOR_USER.value
                    run.run_output = output
                    self.events.emit(
                        run,
                        AgentEventType.USER_ACTION_REQUIRED,
                        {"campaign_id": output.get("campaign_id")},
                    )
                    return await self.repository.checkpoint(run)
                run = await self.repository.checkpoint(run)
                external_status = await self.repository.get_status(run.id)
                if external_status in {
                    AgentRunStatus.PAUSED.value,
                    AgentRunStatus.CANCELLED.value,
                }:
                    return await self.get_run(run.id)
            return run
        except TimeoutError:
            return await self._timeout(run_id)
        except Exception as exc:
            return await self._fail(run_id, str(exc))

    async def _execute_with_retry(
        self,
        run: AgentRun,
        state: AgentState,
        tool: AgentTool,
        tool_input: dict[str, Any],
        remaining: float,
    ) -> tuple[dict[str, Any], AgentRun, AgentState]:
        manifest = tool.get_manifest()
        phase = state.phase
        allowed = self.exposure.get_allowed_tools(
            phase,
            [item.get_manifest() for item in self.registry.catalog()],
        )
        required = list(manifest.capabilities) or state.required_capabilities
        matches = self.matcher.match(required, allowed)
        selected_match = next(
            (item for item in matches if item.tool_name == tool.name),
            None,
        )
        match_confidence = selected_match.confidence if selected_match else 0.0
        budget = ToolBudget(
            max_tool_calls=run.max_steps,
            max_retry_per_tool=run.max_retries,
        )
        last_error = "Tool execution failed"
        tool_deadline = perf_counter() + remaining
        retry_policy = RetryPolicy(max_attempts=run.max_retries + 1)
        for attempt in range(1, run.max_retries + 2):
            if state.step_sequence >= run.max_steps:
                raise AgentExecutionError("Agent reached max_steps during retry")

            campaign_result = AgentMemory.result(run.memory, "create_campaign")
            candidate_ids = {
                str(item.get("job_id"))
                for item in campaign_result.get("candidates", [])
                if isinstance(item, dict) and item.get("job_id")
            }
            requested_job_ids = {
                str(job_id)
                for job_id in tool_input.get("job_ids", state.selected_job_ids)
                if job_id
            }
            validation = self.call_validator.validate(
                manifest,
                tool.input_schema,
                tool_input,
                phase=phase,
                history=state.call_history,
                calls_used=state.tool_call_count,
                budget=budget,
                attempt=attempt,
                confirmation_granted=state.approval_granted,
                explicit_authorization=state.approval_granted,
                precondition_context={
                    "resume_exists": bool(run.run_input.get("resume_id")),
                    "campaign_exists": bool(
                        run.campaign_id or AgentMemory.result(run.memory, "create_campaign")
                    ),
                    "selected_jobs_exist": bool(
                        requested_job_ids
                        and (not candidate_ids or requested_job_ids.issubset(candidate_ids))
                    ),
                    "user_confirmed": state.approval_granted,
                    "not_already_queued": not bool(
                        AgentMemory.result(run.memory, "queue_application")
                    ),
                },
            )
            critique = None
            if manifest.risk_level.value in {"HIGH", "CRITICAL"} or match_confidence < 0.6:
                critique = self.critic.review(
                    manifest,
                    match_confidence=match_confidence,
                    phase=phase,
                    confirmation_granted=state.approval_granted,
                )
                if not critique["approved"]:
                    validation = validation.__class__(
                        **{
                            **validation.__dict__,
                            "valid": False,
                            "reason": critique["issue"],
                        }
                    )
            trace = {
                "trace_id": str(uuid4()),
                "task_id": str(run.id),
                "agent_state": phase,
                "user_goal": str(run.run_input.get("goal", "")),
                "required_capabilities": required,
                "manifest": {
                    "risk_level": manifest.risk_level.value,
                    "cost_level": manifest.cost_level,
                    "latency_level": manifest.latency_level,
                    "requires_confirmation": manifest.requires_confirmation,
                    "preconditions": list(manifest.preconditions),
                    "postconditions": list(manifest.postconditions),
                },
                "tool_decision": {
                    "selected_tool": tool.name,
                    "confidence": match_confidence,
                    "alternatives": [
                        {
                            "tool": item.tool_name,
                            "confidence": item.confidence,
                        }
                        for item in matches[:3]
                        if item.tool_name != tool.name
                    ],
                    "reason": "static plan retained for backwards compatibility; manifest matched",
                },
                "validation": validation.as_dict(),
                "critic": critique,
            }
            state.last_governance_trace = trace
            idempotency_key = (
                f"{run.id}:{state.next_step}:"
                f"{canonical_tool_signature(tool.name, validation.normalized_arguments)}"
            )
            previous = await self.repository.get_latest_tool_invocation(
                run.id, idempotency_key
            )
            if previous is not None and previous.status == "SUCCESS":
                recovered_output = dict(previous.result or {})
                trace["execution"] = {
                    "status": "SUCCESS",
                    "latency_ms": 0,
                    "recovered_from_invocation": str(previous.id),
                    "idempotent_replay": True,
                }
                state.last_governance_trace = trace
                state.call_history = ToolCallHistory.append(
                    state.call_history,
                    tool.name,
                    validation.normalized_arguments,
                    status="RECOVERED_SUCCESS",
                    result={"invocation_id": str(previous.id)},
                )
                run.agent_state = state.dump()
                run.memory = AgentMemory.record_governance(run.memory, trace)
                run = await self.repository.checkpoint(run)
                return recovered_output, run, state
            if (
                previous is not None
                and previous.status == "RUNNING"
                and (manifest.requires_confirmation or "write" in manifest.tags)
            ):
                previous.status = "FAILED"
                previous.retryable = False
                previous.error_code = "ambiguous_side_effect"
                previous.error_message = (
                    "Worker interrupted after a write tool started; automatic replay was blocked"
                )
                previous.completed_at = datetime.now(UTC)
                await self.session.commit()
                raise AgentExecutionError(
                    f"Tool {tool.name} may already have changed data; "
                    "automatic replay was blocked and manual review is required"
                )
            if not validation.valid:
                state.step_sequence += 1
                step = AgentStep(
                    run_id=run.id,
                    sequence=state.step_sequence,
                    step_type="tool",
                    tool_name=tool.name,
                    step_input=tool_input,
                    step_output={"governance": trace},
                    status=AgentStepStatus.FAILED.value,
                    attempt=attempt,
                    error=f"Tool call rejected: {validation.reason}",
                )
                self.repository.add_step(step)
                self.repository.add_tool_invocation(
                    AgentToolInvocation(
                        run_id=run.id,
                        step_id=step.id,
                        call_id=trace["trace_id"],
                        idempotency_key=idempotency_key,
                        tool_name=tool.name,
                        arguments=validation.normalized_arguments,
                        status="REJECTED",
                        attempt=attempt,
                        retryable=False,
                        error_code="policy_rejected",
                        error_message=validation.reason,
                        started_at=datetime.now(UTC),
                        completed_at=datetime.now(UTC),
                    )
                )
                self.events.emit(run, AgentEventType.TOOL_REJECTED, trace)
                run.memory = AgentMemory.record_governance(run.memory, trace)
                run.agent_state = state.dump()
                await self.repository.checkpoint(run)
                raise AgentExecutionError(
                    f"Tool {tool.name} rejected: {validation.reason or 'validation failed'}"
                )

            state.tool_call_count += 1
            state.call_history = ToolCallHistory.append(
                state.call_history,
                tool.name,
                validation.normalized_arguments,
                status="STARTED",
            )
            state.step_sequence += 1
            step = AgentStep(
                run_id=run.id,
                sequence=state.step_sequence,
                step_type="tool",
                tool_name=tool.name,
                step_input=tool_input,
                step_output={},
                status=AgentStepStatus.RUNNING.value,
                attempt=attempt,
            )
            self.repository.add_step(step)
            invocation = AgentToolInvocation(
                run_id=run.id,
                step_id=step.id,
                call_id=trace["trace_id"],
                idempotency_key=idempotency_key,
                tool_name=tool.name,
                arguments=validation.normalized_arguments,
                status="RUNNING",
                attempt=attempt,
                started_at=datetime.now(UTC),
            )
            self.repository.add_tool_invocation(invocation)
            self.events.emit(
                run,
                AgentEventType.STEP_STARTED,
                {
                    "sequence": state.step_sequence,
                    "tool_name": tool.name,
                    "attempt": attempt,
                    "governance": trace,
                },
            )
            run.agent_state = state.dump()
            run = await self.repository.checkpoint(run)
            run_id = run.id
            step_id = step.id
            started = perf_counter()
            try:
                attempt_timeout = min(
                    self.settings.agent_tool_timeout_seconds,
                    max(0.0, tool_deadline - perf_counter()),
                )
                if attempt_timeout <= 0:
                    raise TimeoutError(f"Tool {tool.name} exceeded the Agent deadline")
                execution = await asyncio.wait_for(
                    self.executor.execute(tool.name, tool_input), timeout=attempt_timeout
                )
                if execution.execution_status != "SUCCESS":
                    if execution.execution_status == "TIMEOUT":
                        raise TimeoutError(execution.error or f"Tool {tool.name} timed out")
                    raise RuntimeError(execution.error or f"Tool {tool.name} failed")
                output = execution.data
                result_verification = self.result_verifier.verify(
                    tool.name,
                    validation.normalized_arguments,
                    output,
                )
                trace["execution"] = {
                    "status": execution.execution_status.value,
                    "latency_ms": round((perf_counter() - started) * 1000, 2),
                    "error": execution.error,
                }
                trace["result_verification"] = result_verification.as_dict()
                state.last_governance_trace = trace
                state.call_history = ToolCallHistory.append(
                    state.call_history,
                    tool.name,
                    validation.normalized_arguments,
                    status=result_verification.semantic_status.value,
                    result=result_verification.as_dict(),
                )
                run = await self.get_run(run.id)
                persisted_step = next(item for item in run.steps if item.id == step.id)
                persisted_step.step_output = output
                persisted_step.latency_ms = round((perf_counter() - started) * 1000, 2)
                run.memory = AgentMemory.record_governance(run.memory, trace)
                run.agent_state = state.dump()
                if not result_verification.valid:
                    last_error = (
                        f"Tool {tool.name} result verification failed: "
                        f"{result_verification.reason or 'goal relevance is insufficient'}"
                    )
                    persisted_step.status = AgentStepStatus.FAILED.value
                    persisted_step.error = last_error
                    persisted_invocation = await self.repository.get_tool_invocation(
                        run.id, idempotency_key, attempt
                    )
                    if persisted_invocation is not None:
                        persisted_invocation.status = "FAILED"
                        persisted_invocation.result = output
                        persisted_invocation.retryable = False
                        persisted_invocation.error_code = "semantic_verification_failed"
                        persisted_invocation.error_message = last_error
                        persisted_invocation.latency_ms = persisted_step.latency_ms
                        persisted_invocation.completed_at = datetime.now(UTC)
                    recovery_action = self.recovery.decide(
                        result_verification=result_verification,
                        attempt=attempt,
                        max_retries=run.max_retries,
                    )
                    replacement = self._select_replan_tool(tool.name, matches)
                    if recovery_action == RecoveryAction.REPLAN and replacement is not None:
                        state.plan[state.next_step] = replacement.tool_name
                        trace["replanned_to"] = replacement.tool_name
                        run.agent_state = state.dump()
                    self.events.emit(
                        run,
                        AgentEventType.TOOL_REPLANNED,
                        {
                            **trace,
                            "recovery_action": recovery_action.value,
                        },
                    )
                    self.events.emit(
                        run,
                        AgentEventType.STEP_FAILED,
                        {
                            "sequence": state.step_sequence,
                            "tool_name": tool.name,
                            "error": last_error,
                        },
                    )
                    await self.repository.checkpoint(run)
                    if replacement is not None and recovery_action == RecoveryAction.REPLAN:
                        raise AgentReplanRequested(
                            f"Replanned {tool.name} to {replacement.tool_name}"
                        )
                    break
                persisted_step.status = AgentStepStatus.COMPLETED.value
                persisted_invocation = await self.repository.get_tool_invocation(
                    run.id, idempotency_key, attempt
                )
                if persisted_invocation is not None:
                    persisted_invocation.status = "SUCCESS"
                    persisted_invocation.result = output
                    persisted_invocation.latency_ms = persisted_step.latency_ms
                    persisted_invocation.completed_at = datetime.now(UTC)
                self.events.emit(
                    run,
                    AgentEventType.STEP_FINISHED,
                    {
                        "sequence": state.step_sequence,
                        "tool_name": tool.name,
                        "latency_ms": persisted_step.latency_ms,
                        "result_verification": result_verification.as_dict(),
                    },
                )
                run = await self.repository.checkpoint(run)
                return output, run, state
            except TimeoutError:
                last_error = f"Tool {tool.name} timed out"
                run = await self._mark_step_failed(run_id, step_id, last_error, started)
                await self._mark_invocation_failed(
                    run_id,
                    idempotency_key,
                    attempt,
                    error_code="timeout",
                    error_message=last_error,
                    retryable=True,
                    started=started,
                )
                state.call_history = ToolCallHistory.append(
                    state.call_history,
                    tool.name,
                    validation.normalized_arguments,
                    status="TIMEOUT",
                )
                state.last_governance_trace["execution"] = {
                    "status": "TIMEOUT",
                    "latency_ms": round((perf_counter() - started) * 1000, 2),
                    "error": last_error,
                }
                run.memory = AgentMemory.record_governance(run.memory, state.last_governance_trace)
                run.agent_state = state.dump()
                await self.repository.checkpoint(run)
                if not should_retry(
                    policy=retry_policy,
                    attempt=attempt,
                    error_code="timeout",
                    retryable=True,
                ):
                    raise
                delay = retry_delay_ms(retry_policy, attempt, seed=state.step_sequence)
                if delay / 1000 >= tool_deadline - perf_counter():
                    raise TimeoutError(f"Tool {tool.name} retry exceeds the Agent deadline")
                await asyncio.sleep(delay / 1000)
            except Exception as exc:
                last_error = str(exc)
                run = await self._mark_step_failed(run_id, step_id, last_error, started)
                error_code, retryable = classify_tool_error(exc)
                await self._mark_invocation_failed(
                    run_id,
                    idempotency_key,
                    attempt,
                    error_code=error_code,
                    error_message=last_error,
                    retryable=retryable,
                    started=started,
                )
                state.call_history = ToolCallHistory.append(
                    state.call_history,
                    tool.name,
                    validation.normalized_arguments,
                    status="FAILED",
                )
                state.last_governance_trace["execution"] = {
                    "status": "FAILED",
                    "latency_ms": round((perf_counter() - started) * 1000, 2),
                    "error": last_error,
                }
                run.memory = AgentMemory.record_governance(run.memory, state.last_governance_trace)
                run.agent_state = state.dump()
                await self.repository.checkpoint(run)
                decision = self.recovery.decide(
                    exc,
                    attempt=attempt,
                    max_retries=run.max_retries,
                )
                retry_allowed = should_retry(
                    policy=retry_policy,
                    attempt=attempt,
                    error_code=error_code,
                    retryable=retryable,
                )
                if (
                    decision != RecoveryAction.RETRY
                    or not retry_allowed
                    or manifest.requires_confirmation
                    or "write" in manifest.tags
                ):
                    break
                delay = retry_delay_ms(retry_policy, attempt, seed=state.step_sequence)
                if delay / 1000 >= tool_deadline - perf_counter():
                    raise TimeoutError(f"Tool {tool.name} retry exceeds the Agent deadline")
                await asyncio.sleep(delay / 1000)
        raise AgentExecutionError(f"Tool {tool.name} failed: {last_error}")

    async def _mark_step_failed(
        self,
        run_id: UUID,
        step_id: UUID,
        error: str,
        started: float,
    ) -> AgentRun:
        await self.session.rollback()
        run = await self.get_run(run_id)
        step = next(item for item in run.steps if item.id == step_id)
        step.status = AgentStepStatus.FAILED.value
        step.error = error
        step.latency_ms = round((perf_counter() - started) * 1000, 2)
        self.events.emit(
            run,
            AgentEventType.STEP_FAILED,
            {"sequence": step.sequence, "tool_name": step.tool_name, "error": error},
        )
        return await self.repository.checkpoint(run)

    async def _mark_invocation_failed(
        self,
        run_id: UUID,
        idempotency_key: str,
        attempt: int,
        *,
        error_code: str,
        error_message: str,
        retryable: bool,
        started: float,
    ) -> None:
        invocation = await self.repository.get_tool_invocation(run_id, idempotency_key, attempt)
        if invocation is None:
            return
        invocation.status = "FAILED"
        invocation.retryable = retryable
        invocation.error_code = error_code
        invocation.error_message = error_message
        invocation.latency_ms = round((perf_counter() - started) * 1000, 2)
        invocation.completed_at = datetime.now(UTC)
        await self.session.commit()

    async def _complete(self, run: AgentRun) -> AgentRun:
        state = AgentState.load(run.agent_state)
        state.phase = GovernancePhase.COMPLETE.value
        queue_result = AgentMemory.result(run.memory, "queue_application")
        goal_verification = self.goal_validator.verify(
            str(run.run_input.get("goal", "")),
            run.memory,
        )
        run.finished_at = datetime.now(UTC)
        run.run_output = {
            **run.run_output,
            "approved": bool(queue_result),
            "campaign_id": run.memory.get("session", {}).get("campaign_id"),
            "queued_count": queue_result.get("queued_count", 0),
            "goal_verification": goal_verification.as_dict(),
        }
        run.agent_state = state.dump()
        if goal_verification.goal_completed:
            run.status = AgentRunStatus.COMPLETED.value
            self.events.emit(run, AgentEventType.RUN_COMPLETED, run.run_output)
        else:
            run.status = AgentRunStatus.FAILED.value
            run.error = "Agent goal verification failed: " + ", ".join(
                goal_verification.missing_requirements
            )
            self.events.emit(
                run,
                AgentEventType.RUN_FAILED,
                {**run.run_output, "error": run.error},
            )
        return await self.repository.checkpoint(run)

    async def _fail(self, run_id: UUID, error: str) -> AgentRun:
        await self.session.rollback()
        run = await self.get_run(run_id)
        run.status = AgentRunStatus.FAILED.value
        run.error = error
        run.finished_at = datetime.now(UTC)
        self.events.emit(run, AgentEventType.RUN_FAILED, {"error": error})
        return await self.repository.checkpoint(run)

    async def _timeout(self, run_id: UUID) -> AgentRun:
        await self.session.rollback()
        run = await self.get_run(run_id)
        run.status = AgentRunStatus.TIMED_OUT.value
        run.error = "Agent execution timed out"
        run.finished_at = datetime.now(UTC)
        self.events.emit(run, AgentEventType.RUN_TIMED_OUT)
        return await self.repository.checkpoint(run)

    @staticmethod
    def _results(run: AgentRun, tool_name: str) -> dict[str, Any]:
        return AgentMemory.result(run.memory, tool_name)

    def _search_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        return {
            "keywords": state.criteria["keywords"],
            "cities": state.criteria["cities"],
            "limit": min(300, max(30, state.criteria["max_jobs"] * 5)),
        }

    def _analyze_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        return {"job_ids": self._results(run, "search_jobs").get("job_ids", [])}

    def _resume_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        return {"resume_id": run.run_input.get("resume_id")}

    def _rank_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        return {
            "job_ids": self._results(run, "search_jobs").get("job_ids", []),
            "resume_id": run.run_input.get("resume_id"),
            "min_score": state.criteria["min_score"],
            "final_top_k": state.criteria["max_jobs"],
        }

    def _score_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        job_ids = self._results(run, "search_jobs").get("job_ids", [])
        if not job_ids:
            job_ids = state.selected_job_ids
        return {
            "job_id": job_ids[0] if job_ids else "00000000-0000-0000-0000-000000000000",
            "resume_id": run.run_input.get("resume_id"),
        }

    def _campaign_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        goal = str(run.run_input.get("goal", "Job Search Campaign"))
        return {
            "name": f"Agent · {goal}"[:300],
            "resume_id": run.run_input.get("resume_id"),
            "keywords": state.criteria["keywords"],
            "cities": state.criteria["cities"],
            "min_score": state.criteria["min_score"],
            "max_jobs": state.criteria["max_jobs"],
        }

    def _approval_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        campaign = self._results(run, "create_campaign")
        return {
            "campaign_id": campaign["campaign_id"],
            "candidates": campaign.get("candidates", []),
            "prompt": "请确认要加入投递队列的候选职位。",
        }

    def _queue_input(self, run: AgentRun, state: AgentState) -> dict[str, Any]:
        campaign = self._results(run, "create_campaign")
        return {
            "campaign_id": campaign["campaign_id"],
            "job_ids": state.selected_job_ids,
        }

    def _select_replan_tool(self, failed_tool: str, matches):
        return next(
            (
                item
                for item in matches
                if item.tool_name != failed_tool
                and item.tool_name in self.input_builders
                and item.confidence >= 0.6
            ),
            None,
        )

    @staticmethod
    def _phase_for_tool(tool_name: str) -> GovernancePhase:
        return {
            "search_jobs": GovernancePhase.SEARCH,
            "get_job": GovernancePhase.RETRIEVE,
            "analyze_job": GovernancePhase.ANALYZE,
            "retrieve_resume": GovernancePhase.ANALYZE,
            "score_job": GovernancePhase.ANALYZE,
            "rank_jobs": GovernancePhase.ANALYZE,
            "create_campaign": GovernancePhase.EXECUTE,
            "request_approval": GovernancePhase.VERIFY,
            "queue_application": GovernancePhase.EXECUTE,
        }.get(tool_name, GovernancePhase.PLAN)
