"""Small deterministic policies used by the durable Agent executor."""

from __future__ import annotations

import random
from dataclasses import dataclass
from time import monotonic

from app.schemas.tool_protocol import RetryPolicy

NON_RETRYABLE_CODES = {
    "invalid_arguments",
    "permission_denied",
    "confirmation_required",
    "not_found",
    "policy_rejected",
    "cancelled",
}


def classify_tool_error(error: BaseException) -> tuple[str, bool]:
    name = type(error).__name__.casefold()
    message = str(error).casefold()
    if "timeout" in name or "timed out" in message:
        return "timeout", True
    if "rate" in message and "limit" in message:
        return "rate_limited", True
    if any(token in message for token in ("permission", "unauthorized", "forbidden")):
        return "permission_denied", False
    if any(token in message for token in ("invalid", "validation", "schema")):
        return "invalid_arguments", False
    return "temporary_unavailable", True


def should_retry(*, policy: RetryPolicy, attempt: int, error_code: str, retryable: bool) -> bool:
    return (
        retryable
        and error_code not in NON_RETRYABLE_CODES
        and error_code in policy.retryable_codes
        and attempt < policy.max_attempts
    )


def retry_delay_ms(policy: RetryPolicy, attempt: int, *, seed: int | None = None) -> int:
    base = min(
        policy.max_backoff_ms,
        policy.initial_backoff_ms * policy.multiplier ** max(0, attempt - 1),
    )
    # Jitter avoids synchronized retries; seeded mode keeps tests/evals reproducible.
    return round(base * random.Random(seed).uniform(0.75, 1.25))


@dataclass(frozen=True)
class DeadlineBudget:
    deadline: float

    @classmethod
    def from_timeout(cls, seconds: float) -> DeadlineBudget:
        return cls(deadline=monotonic() + max(0, seconds))

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - monotonic())

    def tool_timeout(self, configured_seconds: float) -> float:
        return min(max(0.0, configured_seconds), self.remaining_seconds)

    @property
    def expired(self) -> bool:
        return self.remaining_seconds <= 0
