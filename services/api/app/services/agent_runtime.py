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
from app.models.entities import AgentEvent, AgentRun, AgentStep
from app.models.states import AgentEventType, AgentRunStatus, AgentStepStatus
from app.repositories.agents import AgentRepository
from app.repositories.matching import MatchingRepository
from app.schemas.agents import AgentRunCreate, AgentRunResumeRequest
from app.services.agent_tools import AgentTool, AgentToolService, ToolRegistry


class AgentRunNotFoundError(ValueError):
    """Raised when an Agent Run does not exist."""


class AgentRunActionError(ValueError):
    """Raised when an Agent Run action is invalid for its current state."""


class AgentExecutionError(RuntimeError):
    """Raised when execution cannot continue safely."""


@dataclass
class AgentState:
    plan: list[str]
    criteria: dict[str, Any]
    next_step: int = 0
    step_sequence: int = 0
    selected_job_ids: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, value: dict[str, Any]) -> AgentState:
        return cls(
            plan=list(value.get("plan", [])),
            criteria=dict(value.get("criteria", {})),
            next_step=int(value.get("next_step", 0)),
            step_sequence=int(value.get("step_sequence", 0)),
            selected_job_ids=list(value.get("selected_job_ids", [])),
        )

    def dump(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "criteria": self.criteria,
            "next_step": self.next_step,
            "step_sequence": self.step_sequence,
            "selected_job_ids": self.selected_job_ids,
        }


class AgentMemory:
    @staticmethod
    def initialize(*, goal: str, resume_id: UUID) -> dict[str, Any]:
        return {
            "working": {"goal": goal, "tool_results": {}},
            "session": {"resume_id": str(resume_id), "campaign_id": None},
        }

    @staticmethod
    def record(memory: dict[str, Any], tool_name: str, output: dict[str, Any]) -> dict[str, Any]:
        updated = {
            "working": dict(memory.get("working", {})),
            "session": dict(memory.get("session", {})),
        }
        results = dict(updated["working"].get("tool_results", {}))
        results[tool_name] = output
        updated["working"]["tool_results"] = results
        if tool_name == "create_campaign":
            updated["session"]["campaign_id"] = output.get("campaign_id")
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
        return AgentState(plan=list(self.plan), criteria=self._criteria(goal))

    @staticmethod
    def _criteria(goal: str) -> dict[str, Any]:
        score_match = re.search(
            r"(?:匹配度|分数|score)\s*[:：]?\s*(\d{1,3})\s*分?\s*(?:以上|起)?"
            r"|(\d{1,3})\s*分\s*(?:以上|起)",
            goal,
            re.I,
        )
        matched_score = next(
            (group for group in score_match.groups() if group is not None), None
        ) if score_match else None
        min_score = min(100.0, float(matched_score)) if matched_score else 70.0
        count_match = re.search(
            r"(?:最多|前|Top)\s*(\d{1,3})\s*(?:个|条)?", goal, re.I
        )
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

    async def execute(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.registry.get(tool_name).execute(payload)


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
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings or get_settings()
        self.repository = AgentRepository(session)
        self.registry: ToolRegistry = AgentToolService(
            session, provider, self.settings
        ).registry()
        self.executor = AgentExecutor(self.registry)
        self.planner = AgentPlanner()
        self.events = AgentEventEmitter(self.repository)
        self.input_builders = {
            "search_jobs": self._search_input,
            "analyze_job": self._analyze_input,
            "retrieve_resume": self._resume_input,
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
            run_input={"goal": payload.goal, "resume_id": str(resume.id)},
            run_output={},
            agent_state=state.dump(),
            memory=AgentMemory.initialize(goal=payload.goal, resume_id=resume.id),
            max_steps=payload.max_steps,
            timeout_seconds=payload.timeout_seconds,
            max_retries=payload.max_retries,
        )
        self.events.emit(run, AgentEventType.RUN_CREATED, {"goal": payload.goal})
        run = await self.repository.checkpoint(run)
        return await self.start(run.id) if payload.auto_start else run

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
            )
        )
        retried.run_input = {
            **retried.run_input,
            "retry_of": str(source.id),
            "retry_reason": source.error,
        }
        retried = await self.repository.checkpoint(retried)
        return await self.start(retried.id)

    async def _run_until_blocked(self, run: AgentRun) -> AgentRun:
        run_id = run.id
        deadline = perf_counter() + run.timeout_seconds
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
                tool_input = self.input_builders[tool_name](run, state)
                output, run, state = await self._execute_with_retry(
                    run,
                    state,
                    tool,
                    tool_input,
                    remaining,
                )
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
        last_error = "Tool execution failed"
        for attempt in range(1, run.max_retries + 2):
            if state.step_sequence >= run.max_steps:
                raise AgentExecutionError("Agent reached max_steps during retry")
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
            self.events.emit(
                run,
                AgentEventType.STEP_STARTED,
                {"sequence": state.step_sequence, "tool_name": tool.name, "attempt": attempt},
            )
            run.agent_state = state.dump()
            run = await self.repository.checkpoint(run)
            run_id = run.id
            step_id = step.id
            started = perf_counter()
            try:
                output = await asyncio.wait_for(
                    self.executor.execute(tool.name, tool_input), timeout=remaining
                )
                run = await self.get_run(run.id)
                persisted_step = next(item for item in run.steps if item.id == step.id)
                persisted_step.step_output = output
                persisted_step.status = AgentStepStatus.COMPLETED.value
                persisted_step.latency_ms = round((perf_counter() - started) * 1000, 2)
                self.events.emit(
                    run,
                    AgentEventType.STEP_FINISHED,
                    {
                        "sequence": state.step_sequence,
                        "tool_name": tool.name,
                        "latency_ms": persisted_step.latency_ms,
                    },
                )
                run = await self.repository.checkpoint(run)
                return output, run, state
            except TimeoutError:
                last_error = f"Tool {tool.name} timed out"
                await self._mark_step_failed(run_id, step_id, last_error, started)
                raise
            except Exception as exc:
                last_error = str(exc)
                run = await self._mark_step_failed(run_id, step_id, last_error, started)
                if attempt > run.max_retries:
                    break
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

    async def _complete(self, run: AgentRun) -> AgentRun:
        queue_result = AgentMemory.result(run.memory, "queue_application")
        run.status = AgentRunStatus.COMPLETED.value
        run.finished_at = datetime.now(UTC)
        run.run_output = {
            **run.run_output,
            "approved": bool(queue_result),
            "campaign_id": run.memory.get("session", {}).get("campaign_id"),
            "queued_count": queue_result.get("queued_count", 0),
        }
        self.events.emit(run, AgentEventType.RUN_COMPLETED, run.run_output)
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
