from __future__ import annotations

from pydantic import BaseModel, Field


class LLMUsageRead(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    source: str = "not_recorded"
