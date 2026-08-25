from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.states import AgentRunStatus, AgentStepStatus, ApplicationStatus
from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import (
    AgentRuntimeStats,
    ApplicationStatusCount,
    DashboardRead,
    DashboardSummary,
    FunnelStageRead,
)
from app.schemas.usage import LLMUsageRead


class DashboardService:
    def __init__(self, repository: DashboardRepository) -> None:
        self.repository = repository

    async def overview(self) -> DashboardRead:
        raw = await self.repository.snapshot()
        status_counts: dict[str, int] = dict(raw["application_status"])
        submitted = status_counts.get(ApplicationStatus.SUBMITTED.value, 0)
        attention_statuses = {
            ApplicationStatus.CAPTCHA_REQUIRED.value,
            ApplicationStatus.LOGIN_REQUIRED.value,
            ApplicationStatus.PLATFORM_LIMIT.value,
            ApplicationStatus.DOM_CHANGED.value,
            ApplicationStatus.RISK_CONTROL.value,
            ApplicationStatus.UNKNOWN_STATE.value,
            ApplicationStatus.FAILED.value,
        }
        attention = sum(status_counts.get(status, 0) for status in attention_statuses)
        queued = sum(
            status_counts.get(status, 0)
            for status in (
                ApplicationStatus.QUEUED.value,
                ApplicationStatus.EXECUTING.value,
                ApplicationStatus.PAUSED.value,
            )
        )
        approval = status_counts.get(ApplicationStatus.WAITING_APPROVAL.value, 0)
        funnel_counts = [
            ("discovered", "发现职位", raw["jobs_total"]),
            ("high_match", "高匹配职位", raw["high_match_jobs"]),
            ("approval", "等待确认", approval),
            ("queued", "已排队", queued),
            ("submitted", "已投递", submitted),
        ]
        previous = None
        funnel: list[FunnelStageRead] = []
        for key, label, count in funnel_counts:
            funnel.append(
                FunnelStageRead(
                    key=key,
                    label=label,
                    count=count,
                    conversion_rate=(round(count / previous * 100, 2) if previous else None),
                )
            )
            if count > 0:
                previous = count

        runs = raw["agent_runs"]
        steps = [step for run in runs for step in run.steps]
        active_statuses = {
            AgentRunStatus.PENDING.value,
            AgentRunStatus.RUNNING.value,
            AgentRunStatus.PAUSED.value,
            AgentRunStatus.WAITING_FOR_USER.value,
        }
        total_latency = sum(float(step.latency_ms or 0) for step in steps)
        usage = self._aggregate_usage(runs)
        return DashboardRead(
            summary=DashboardSummary(
                jobs_total=raw["jobs_total"],
                high_match_jobs=raw["high_match_jobs"],
                campaigns_total=raw["campaigns_total"],
                campaign_candidates=raw["campaign_candidates"],
                applications_total=sum(status_counts.values()),
                submitted_applications=submitted,
                attention_required=attention,
            ),
            funnel=funnel,
            application_status=[
                ApplicationStatusCount(status=status, count=count)
                for status, count in sorted(status_counts.items())
            ],
            agent=AgentRuntimeStats(
                total_runs=len(runs),
                active_runs=sum(run.status in active_statuses for run in runs),
                completed_runs=sum(run.status == AgentRunStatus.COMPLETED.value for run in runs),
                failed_runs=sum(
                    run.status
                    in {AgentRunStatus.FAILED.value, AgentRunStatus.TIMED_OUT.value}
                    for run in runs
                ),
                total_steps=len(steps),
                failed_steps=sum(step.status == AgentStepStatus.FAILED.value for step in steps),
                retry_count=sum(max(int(step.attempt) - 1, 0) for step in steps),
                average_latency_ms=round(total_latency / len(steps), 2) if steps else 0.0,
            ),
            token_usage=LLMUsageRead.model_validate(usage),
            refreshed_at=datetime.now(UTC),
        )

    @staticmethod
    def _aggregate_usage(runs: list[Any]) -> dict[str, Any]:
        prompt = 0
        completion = 0
        cost: float | None = None
        source = "not_recorded"
        usage_seen = False
        for run in runs:
            results = run.memory.get("working", {}).get("tool_results", {})
            for result in results.values():
                usage = result.get("token_usage") if isinstance(result, dict) else None
                if not isinstance(usage, dict):
                    continue
                prompt += int(usage.get("prompt_tokens", 0))
                completion += int(usage.get("completion_tokens", 0))
                value = usage.get("cost_usd")
                if not usage_seen:
                    cost = float(value) if value is not None else None
                elif value is None or cost is None:
                    cost = None
                else:
                    cost += float(value)
                usage_seen = True
                source = str(usage.get("source", source))
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cost_usd": cost,
            "source": source,
        }
