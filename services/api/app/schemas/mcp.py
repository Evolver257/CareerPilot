from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class MCPConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    namespace: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    transport: Literal["streamable_http", "stdio"]
    endpoint: str | None = Field(default=None, max_length=1000)
    command: str | None = Field(default=None, max_length=500)
    arguments: list[str] = Field(default_factory=list, max_length=30)
    credentials: dict[str, str] = Field(default_factory=dict)
    enabled: bool = False
    permission_scopes: list[str] = Field(default_factory=list, max_length=30)
    allowed_tools: list[str] = Field(default_factory=list, max_length=200)
    blocked_tools: list[str] = Field(default_factory=list, max_length=200)
    connect_timeout: float = Field(default=10, ge=0.5, le=60)
    tool_timeout: float = Field(default=30, ge=0.5, le=300)


class MCPConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint: str | None = Field(default=None, max_length=1000)
    command: str | None = Field(default=None, max_length=500)
    arguments: list[str] | None = Field(default=None, max_length=30)
    credentials: dict[str, str] | None = None
    enabled: bool | None = None
    permission_scopes: list[str] | None = Field(default=None, max_length=30)
    allowed_tools: list[str] | None = Field(default=None, max_length=200)
    blocked_tools: list[str] | None = Field(default=None, max_length=200)
    connect_timeout: float | None = Field(default=None, ge=0.5, le=60)
    tool_timeout: float | None = Field(default=None, ge=0.5, le=300)


class MCPConnectionRead(BaseModel):
    id: UUID
    name: str
    namespace: str
    transport: str
    endpoint: str | None
    command: str | None
    arguments: list[str]
    credentials_configured: bool
    credentials_hint: str | None
    enabled: bool
    status: str
    permission_scopes: list[str]
    allowed_tools: list[str]
    blocked_tools: list[str]
    connect_timeout: float
    tool_timeout: float
    last_health_check: datetime | None
    created_at: datetime
    updated_at: datetime


class MCPToolRead(BaseModel):
    id: UUID
    remote_name: str
    canonical_name: str
    description: str
    input_schema: dict
    output_schema: dict
    schema_hash: str
    active: bool
    last_seen_at: datetime


class MCPDiscoveryRead(BaseModel):
    connection: MCPConnectionRead
    tools: list[MCPToolRead]
    changed: int

