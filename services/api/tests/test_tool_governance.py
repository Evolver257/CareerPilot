from app.services.tool_governance import (
    GoalValidator,
    GovernancePhase,
    ToolBudget,
    ToolManifest,
    ToolNeedClassifier,
    ToolPolicyEngine,
    ToolResultVerifier,
    ToolRiskLevel,
    ToolSemanticStatus,
)
from evaluation.tool_governance import cases, run


def test_tool_governance_eval_covers_more_than_30_cases_and_passes():
    result = run()

    assert len(cases()) >= 30
    assert result["total"] == len(cases())
    assert result["passed"] == result["total"]
    assert result["pass_rate"] == 1
    assert result["failures"] == []


def test_tool_governance_eval_reports_each_guardrail_family():
    metrics = run()["metrics"]

    assert metrics["schema_failure_rate"] > 0
    assert metrics["semantic_argument_error_rate"] > 0
    assert metrics["policy_rejection_rate"] > 0
    assert metrics["duplicate_rejection_rate"] > 0
    assert metrics["budget_rejection_rate"] > 0
    assert metrics["high_risk_confirmation_rejection_rate"] > 0
    assert metrics["execution_success_rate"] is None
    assert metrics["semantic_verification_rate"] is None
    assert metrics["goal_completion_rate"] is None


def test_need_tool_classifier_keeps_general_questions_local_and_detects_freshness():
    classifier = ToolNeedClassifier()

    assert classifier.classify("Redis缓存穿透是什么").need_tool is False
    decision = classifier.classify("今天 OpenAI 发布了什么？")
    assert decision.need_tool is True
    assert "realtime_information" in decision.required_capabilities


def test_budget_supports_search_and_cost_limits():
    budget = ToolBudget(max_tool_calls=5, max_search_calls=1, max_total_cost=2)

    assert budget.check(0, tool_name="search_jobs", tool_cost_level="LOW")[0]
    assert not budget.check(
        1,
        search_calls_used=1,
        tool_name="search_jobs",
        tool_cost_level="LOW",
    )[0]
    assert not budget.check(0, tool_name="rank_jobs", tool_cost_level="HIGH")[0]


def test_critical_policy_requires_explicit_authorization_and_goal_verifier_is_separate():
    manifest = ToolManifest(
        name="delete_workspace",
        description="Delete workspace data",
        risk_level=ToolRiskLevel.CRITICAL,
        allowed_states=(GovernancePhase.EXECUTE.value,),
    )
    policy = ToolPolicyEngine()

    assert not policy.check(manifest, phase=GovernancePhase.EXECUTE.value).allowed
    assert policy.check(
        manifest,
        phase=GovernancePhase.EXECUTE.value,
        explicit_authorization=True,
    ).allowed

    goal = GoalValidator().verify(
        "find and rank jobs",
        {
            "working": {
                "tool_results": {
                    "search_jobs": {"count": 1},
                    "retrieve_resume": {"resume_id": "resume"},
                    "rank_jobs": {"count": 1},
                }
            }
        },
    )
    assert goal.goal_completed is True
    empty_goal = GoalValidator().verify(
        "find and rank jobs",
        {
            "working": {
                "tool_results": {
                    "search_jobs": {"count": 0},
                    "retrieve_resume": {"resume_id": "resume"},
                    "rank_jobs": {"count": 0},
                }
            }
        },
    )
    assert empty_goal.goal_completed is False
    assert "matching jobs" in empty_goal.missing_requirements


def test_result_verifier_distinguishes_partial_empty_search_from_invalid_shape():
    verifier = ToolResultVerifier()

    empty = verifier.verify("search_jobs", {}, {"count": 0, "job_ids": []})
    invalid = verifier.verify("search_jobs", {}, {"count": 2, "job_ids": []})
    assert empty.valid is True
    assert empty.semantic_status is ToolSemanticStatus.PARTIAL
    assert invalid.valid is False
