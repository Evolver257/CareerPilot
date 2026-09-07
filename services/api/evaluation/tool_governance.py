"""Deterministic evaluation suite for Tool Call Verification.

The suite intentionally stops before external tool execution.  It measures
whether proposed calls are correctly accepted or rejected by schema,
semantic, policy, duplicate, confirmation, and budget guardrails.  Runtime
success, result semantics, and end-goal completion are measured separately by
AgentRun traces and are reported as ``None`` here rather than being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.services.agent_tools import TOOL_INPUT_SCHEMAS, TOOL_MANIFESTS
from app.services.tool_governance import (
    GovernancePhase,
    ToolBudget,
    ToolCallHistory,
    ToolCallValidator,
)

_JOB_ID = UUID("00000000-0000-0000-0000-000000000001")
_JOB_ID_2 = UUID("00000000-0000-0000-0000-000000000002")
_RESUME_ID = UUID("00000000-0000-0000-0000-000000000003")
_CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000004")


@dataclass(frozen=True)
class ToolGovernanceCase:
    case_id: str
    tool_name: str
    payload: dict[str, Any]
    phase: str
    expected_valid: bool
    confirmation_granted: bool = False
    explicit_authorization: bool = False
    user_authorized: bool = True
    calls_used: int = 0
    max_tool_calls: int = 10
    history: tuple[dict[str, Any], ...] = ()
    preconditions: dict[str, bool] | None = None


def _duplicate_history(tool_name: str, payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    return (
        {
            "signature": ToolCallHistory.signature(tool_name, payload),
            "tool": tool_name,
            "arguments": payload,
            "status": "SUCCESS",
        },
    )


def cases() -> list[ToolGovernanceCase]:
    """Return 36 stable cases spanning acceptance and rejection paths."""

    search = {
        "keywords": ["AI Agent"],
        "cities": ["北京"],
        "limit": 20,
        "platforms": [],
    }
    rank = {"job_ids": [_JOB_ID], "resume_id": _RESUME_ID, "min_score": 70, "final_top_k": 10}
    campaign = {
        "name": "AI Agent 实习投递计划",
        "resume_id": _RESUME_ID,
        "keywords": ["AI Agent"],
        "cities": ["北京"],
        "min_score": 70,
        "max_jobs": 10,
    }
    return [
        ToolGovernanceCase(
            "search-valid-keyword", "search_jobs", search, GovernancePhase.SEARCH.value, True
        ),
        ToolGovernanceCase(
            "search-valid-city",
            "search_jobs",
            {**search, "keywords": [], "cities": ["上海"]},
            GovernancePhase.SEARCH.value,
            True,
        ),
        ToolGovernanceCase(
            "search-valid-platform",
            "search_jobs",
            {**search, "keywords": [], "cities": [], "platforms": ["boss"]},
            GovernancePhase.SEARCH.value,
            True,
        ),
        ToolGovernanceCase(
            "search-no-constraint",
            "search_jobs",
            {**search, "keywords": [], "cities": [], "platforms": []},
            GovernancePhase.SEARCH.value,
            False,
        ),
        ToolGovernanceCase(
            "search-blank-keyword",
            "search_jobs",
            {**search, "keywords": [" "]},
            GovernancePhase.SEARCH.value,
            False,
        ),
        ToolGovernanceCase(
            "search-limit-too-large",
            "search_jobs",
            {**search, "limit": 301},
            GovernancePhase.SEARCH.value,
            False,
        ),
        ToolGovernanceCase(
            "search-wrong-phase", "search_jobs", search, GovernancePhase.ANALYZE.value, False
        ),
        ToolGovernanceCase(
            "search-unauthorized",
            "search_jobs",
            search,
            GovernancePhase.SEARCH.value,
            False,
            user_authorized=False,
        ),
        ToolGovernanceCase(
            "job-valid", "get_job", {"job_id": _JOB_ID}, GovernancePhase.RETRIEVE.value, True
        ),
        ToolGovernanceCase(
            "job-invalid-uuid",
            "get_job",
            {"job_id": "not-a-uuid"},
            GovernancePhase.RETRIEVE.value,
            False,
        ),
        ToolGovernanceCase("job-missing-id", "get_job", {}, GovernancePhase.RETRIEVE.value, False),
        ToolGovernanceCase(
            "job-wrong-phase", "get_job", {"job_id": _JOB_ID}, GovernancePhase.SEARCH.value, False
        ),
        ToolGovernanceCase(
            "analyze-valid",
            "analyze_job",
            {"job_ids": [_JOB_ID, _JOB_ID_2]},
            GovernancePhase.ANALYZE.value,
            True,
        ),
        ToolGovernanceCase(
            "analyze-duplicate-ids",
            "analyze_job",
            {"job_ids": [_JOB_ID, _JOB_ID]},
            GovernancePhase.ANALYZE.value,
            False,
        ),
        ToolGovernanceCase(
            "analyze-wrong-phase",
            "analyze_job",
            {"job_ids": [_JOB_ID]},
            GovernancePhase.RETRIEVE.value,
            False,
        ),
        ToolGovernanceCase(
            "resume-valid",
            "retrieve_resume",
            {"resume_id": _RESUME_ID},
            GovernancePhase.ANALYZE.value,
            True,
        ),
        ToolGovernanceCase(
            "resume-default",
            "retrieve_resume",
            {"resume_id": None},
            GovernancePhase.ANALYZE.value,
            True,
        ),
        ToolGovernanceCase(
            "resume-wrong-phase",
            "retrieve_resume",
            {"resume_id": _RESUME_ID},
            GovernancePhase.SEARCH.value,
            False,
        ),
        ToolGovernanceCase(
            "score-valid",
            "score_job",
            {"job_id": _JOB_ID, "resume_id": _RESUME_ID},
            GovernancePhase.ANALYZE.value,
            True,
        ),
        ToolGovernanceCase(
            "score-missing-job",
            "score_job",
            {"resume_id": _RESUME_ID},
            GovernancePhase.ANALYZE.value,
            False,
        ),
        ToolGovernanceCase(
            "score-invalid-resume",
            "score_job",
            {"job_id": _JOB_ID, "resume_id": "bad"},
            GovernancePhase.ANALYZE.value,
            False,
        ),
        ToolGovernanceCase("rank-valid", "rank_jobs", rank, GovernancePhase.ANALYZE.value, True),
        ToolGovernanceCase(
            "rank-empty", "rank_jobs", {**rank, "job_ids": []}, GovernancePhase.ANALYZE.value, True
        ),
        ToolGovernanceCase(
            "rank-invalid-score",
            "rank_jobs",
            {**rank, "min_score": 101},
            GovernancePhase.ANALYZE.value,
            False,
        ),
        ToolGovernanceCase(
            "rank-budget-exhausted",
            "rank_jobs",
            rank,
            GovernancePhase.ANALYZE.value,
            False,
            calls_used=10,
            max_tool_calls=10,
        ),
        ToolGovernanceCase(
            "campaign-valid", "create_campaign", campaign, GovernancePhase.EXECUTE.value, True
        ),
        ToolGovernanceCase(
            "campaign-blank-name",
            "create_campaign",
            {**campaign, "name": " "},
            GovernancePhase.EXECUTE.value,
            False,
        ),
        ToolGovernanceCase(
            "campaign-bad-max-jobs",
            "create_campaign",
            {**campaign, "max_jobs": 0},
            GovernancePhase.EXECUTE.value,
            False,
        ),
        ToolGovernanceCase(
            "campaign-no-resume",
            "create_campaign",
            campaign,
            GovernancePhase.EXECUTE.value,
            False,
            preconditions={"resume_exists": False},
        ),
        ToolGovernanceCase(
            "campaign-wrong-phase",
            "create_campaign",
            campaign,
            GovernancePhase.ANALYZE.value,
            False,
        ),
        ToolGovernanceCase(
            "approval-valid",
            "request_approval",
            {"campaign_id": _CAMPAIGN_ID, "candidates": [], "prompt": "请确认投递"},
            GovernancePhase.VERIFY.value,
            True,
        ),
        ToolGovernanceCase(
            "approval-blank-prompt",
            "request_approval",
            {"campaign_id": _CAMPAIGN_ID, "candidates": [], "prompt": ""},
            GovernancePhase.VERIFY.value,
            False,
        ),
        ToolGovernanceCase(
            "queue-needs-confirmation",
            "queue_application",
            {"campaign_id": _CAMPAIGN_ID, "job_ids": [_JOB_ID]},
            GovernancePhase.EXECUTE.value,
            False,
        ),
        ToolGovernanceCase(
            "queue-confirmed",
            "queue_application",
            {"campaign_id": _CAMPAIGN_ID, "job_ids": [_JOB_ID]},
            GovernancePhase.EXECUTE.value,
            True,
            confirmation_granted=True,
            explicit_authorization=True,
        ),
        ToolGovernanceCase(
            "queue-empty",
            "queue_application",
            {"campaign_id": _CAMPAIGN_ID, "job_ids": []},
            GovernancePhase.EXECUTE.value,
            False,
            confirmation_granted=True,
        ),
        ToolGovernanceCase(
            "queue-duplicate",
            "queue_application",
            {"campaign_id": _CAMPAIGN_ID, "job_ids": [_JOB_ID]},
            GovernancePhase.EXECUTE.value,
            False,
            confirmation_granted=True,
            explicit_authorization=True,
            history=_duplicate_history(
                "queue_application", {"campaign_id": _CAMPAIGN_ID, "job_ids": [_JOB_ID]}
            ),
        ),
        ToolGovernanceCase(
            "queue-bad-campaign",
            "queue_application",
            {"campaign_id": "bad", "job_ids": [_JOB_ID]},
            GovernancePhase.EXECUTE.value,
            False,
            confirmation_granted=True,
            explicit_authorization=True,
        ),
        ToolGovernanceCase(
            "queue-unauthorized",
            "queue_application",
            {"campaign_id": _CAMPAIGN_ID, "job_ids": [_JOB_ID]},
            GovernancePhase.EXECUTE.value,
            False,
            confirmation_granted=True,
            explicit_authorization=True,
            user_authorized=False,
        ),
        ToolGovernanceCase(
            "queue-budget-exhausted",
            "queue_application",
            {"campaign_id": _CAMPAIGN_ID, "job_ids": [_JOB_ID]},
            GovernancePhase.EXECUTE.value,
            False,
            confirmation_granted=True,
            explicit_authorization=True,
            calls_used=5,
            max_tool_calls=5,
        ),
    ]


def run(cases_to_run: list[ToolGovernanceCase] | None = None) -> dict[str, Any]:
    """Evaluate every case without touching a database or external provider."""

    validator = ToolCallValidator()
    evaluated = []
    for case in cases_to_run or cases():
        manifest = TOOL_MANIFESTS[case.tool_name]
        schema = TOOL_INPUT_SCHEMAS[case.tool_name]
        result = validator.validate(
            manifest,
            schema,
            case.payload,
            phase=case.phase,
            history=list(case.history),
            calls_used=case.calls_used,
            budget=ToolBudget(max_tool_calls=case.max_tool_calls),
            confirmation_granted=case.confirmation_granted,
            explicit_authorization=case.explicit_authorization,
            user_authorized=case.user_authorized,
            precondition_context=(
                case.preconditions
                if case.preconditions is not None
                else {name: True for name in manifest.preconditions}
            ),
        )
        passed = result.valid == case.expected_valid
        evaluated.append(
            {
                "case_id": case.case_id,
                "tool": case.tool_name,
                "expected_valid": case.expected_valid,
                "actual_valid": result.valid,
                "passed": passed,
                "validation": result.as_dict(),
            }
        )

    total = len(evaluated)
    rejected = [item for item in evaluated if not item["actual_valid"]]

    def rate(predicate) -> float:
        return (
            round(sum(predicate(item["validation"]) for item in rejected) / total, 4)
            if total
            else 0.0
        )

    return {
        "total": total,
        "passed": sum(item["passed"] for item in evaluated),
        "pass_rate": round(sum(item["passed"] for item in evaluated) / total, 4) if total else 0.0,
        "failures": [item for item in evaluated if not item["passed"]],
        "metrics": {
            "tool_selection_accuracy": None,
            "unnecessary_tool_call_rate": None,
            "wrong_tool_rate": None,
            "argument_accuracy": None,
            "schema_failure_rate": rate(lambda item: not item["schema"]),
            "semantic_argument_error_rate": rate(
                lambda item: item["schema"] and not item["semantic"]
            ),
            "policy_rejection_rate": rate(lambda item: not item["policy"]),
            "duplicate_rejection_rate": rate(lambda item: not item["duplicate"]),
            "budget_rejection_rate": rate(lambda item: not item["budget"]),
            "high_risk_confirmation_rejection_rate": rate(
                lambda item: item["reason"] is not None and "confirmation" in item["reason"]
            ),
            "execution_success_rate": None,
            "semantic_success_rate": None,
            "result_relevance": None,
            "semantic_verification_rate": None,
            "goal_completion_rate": None,
            "average_tool_calls_per_task": None,
            "retry_rate": None,
            "tool_switch_rate": None,
            "high_risk_rejection_rate": rate(
                lambda item: item["reason"] is not None and "confirmation" in item["reason"]
            ),
        },
        "execution_boundary": "pre_call_only; runtime traces measure execution/result/goal metrics",
    }
