from __future__ import annotations

import math
from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """Conservative local estimate used when a provider returns no usage data."""

    return max(1, math.ceil(len(text) / 4)) if text else 0


@dataclass(frozen=True)
class UsageRecord:
    prompt_tokens: int
    completion_tokens: int
    source: str = "estimated"
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageAccumulator:
    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd: float | None = None
        self.source = "not_recorded"
        self._has_usage = False

    def add(self, usage: UsageRecord | None) -> None:
        if usage is None:
            return
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens
        if not self._has_usage:
            self.cost_usd = usage.cost_usd
        elif usage.cost_usd is None or self.cost_usd is None:
            self.cost_usd = None
        else:
            self.cost_usd += usage.cost_usd
        self._has_usage = True
        self.source = usage.source

    def as_dict(self) -> dict[str, int | float | str | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "cost_usd": self.cost_usd,
            "source": self.source,
        }
