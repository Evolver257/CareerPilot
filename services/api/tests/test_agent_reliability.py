import asyncio

from app.schemas.tool_protocol import RetryPolicy
from app.services.agent_reliability import (
    DeadlineBudget,
    classify_tool_error,
    retry_delay_ms,
    should_retry,
)
from app.worker import is_business_terminal, model_for_kind, work_status


def test_error_classification_never_retries_policy_or_argument_failures():
    assert classify_tool_error(ValueError("invalid schema")) == ("invalid_arguments", False)
    assert classify_tool_error(PermissionError("permission denied")) == (
        "permission_denied",
        False,
    )
    assert classify_tool_error(TimeoutError("timed out")) == ("timeout", True)


def test_retry_policy_has_bounded_seeded_backoff():
    policy = RetryPolicy(max_attempts=3, initial_backoff_ms=100, max_backoff_ms=150)
    assert should_retry(policy=policy, attempt=1, error_code="timeout", retryable=True)
    assert not should_retry(policy=policy, attempt=3, error_code="timeout", retryable=True)
    assert not should_retry(
        policy=policy, attempt=1, error_code="invalid_arguments", retryable=True
    )
    assert retry_delay_ms(policy, 2, seed=7) == retry_delay_ms(policy, 2, seed=7)
    assert retry_delay_ms(policy, 2, seed=7) <= 188


def test_deadline_budget_caps_individual_tool_timeout():
    budget = DeadlineBudget.from_timeout(0.05)
    assert 0 < budget.tool_timeout(10) <= 0.05
    asyncio.run(asyncio.sleep(0.06))
    assert budget.expired
    assert budget.tool_timeout(10) == 0


def test_worker_maps_agent_waiting_and_completion_to_successful_work_units():
    assert model_for_kind("agent").__name__ == "AgentRun"
    assert is_business_terminal("agent", "WAITING_FOR_USER")
    assert is_business_terminal("agent", "COMPLETED")
    assert not is_business_terminal("agent", "RUNNING")
    assert work_status("agent", "WAITING_FOR_USER") == "SUCCEEDED"
    assert work_status("agent", "COMPLETED") == "SUCCEEDED"
    assert work_status("agent", "FAILED") == "FAILED"
