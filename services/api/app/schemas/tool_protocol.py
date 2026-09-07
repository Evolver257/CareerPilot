"""Provider-neutral tool messages used by local tools and future MCP tools."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    DENIED = "DENIED"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"


class ToolSource(StrEnum):
    LOCAL = "local"
    MCP = "mcp"


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=10)
    initial_backoff_ms: int = Field(default=250, ge=0, le=60_000)
    max_backoff_ms: int = Field(default=5_000, ge=0, le=300_000)
    multiplier: float = Field(default=2.0, ge=1, le=10)
    retryable_codes: list[str] = Field(
        default_factory=lambda: ["timeout", "rate_limited", "temporary_unavailable"]
    )


class ToolDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,200}$")
    description: str = Field(min_length=1, max_length=4000)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=dict)
    source: ToolSource = ToolSource.LOCAL
    server_id: str | None = None
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"
    permissions: list[str] = Field(default_factory=list)
    timeout_ms: int = Field(default=30_000, ge=100, le=600_000)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    idempotent: bool = True
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextContentBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class JsonContentBlock(BaseModel):
    type: Literal["json"] = "json"
    data: Any


class ResourceContentBlock(BaseModel):
    type: Literal["resource"] = "resource"
    uri: str
    mime_type: str | None = None
    text: str | None = None


ToolContentBlock = TextContentBlock | JsonContentBlock | ResourceContentBlock


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class AgentToolCall(BaseModel):
    call_id: str = Field(min_length=1, max_length=300)
    tool_name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    source: ToolSource = ToolSource.LOCAL
    server_id: str | None = None
    idempotency_key: str | None = None
    parent_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentToolResult(BaseModel):
    call_id: str
    tool_name: str
    status: ToolCallStatus
    content: list[ToolContentBlock] = Field(default_factory=list)
    error: ToolError | None = None
    started_at: str | None = None
    completed_at: str | None = None
    latency_ms: float = Field(default=0, ge=0)
    attempt: int = Field(default=1, ge=1)
    token_usage: dict[str, int] = Field(default_factory=dict)
    cost: float = Field(default=0, ge=0)
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ToolContentBlock] = ""
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    tool_result: AgentToolResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NativeToolResponse(BaseModel):
    text: str = ""
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    stop_reason: str | None = None
    provider: str
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
