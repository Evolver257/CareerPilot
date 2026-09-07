"""MCP client with per-connection isolation and deny-by-default tool exposure."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from app.schemas.tool_protocol import (
    AgentToolCall,
    AgentToolResult,
    JsonContentBlock,
    TextContentBlock,
    ToolCallStatus,
    ToolDefinition,
    ToolError,
    ToolSource,
)


class MCPServerConfig(BaseModel):
    server_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    transport: Literal["streamable_http", "stdio"]
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = False
    allowed_tools: list[str] = Field(default_factory=list)
    permission_scopes: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=30, ge=0.1, le=300)
    max_result_chars: int = Field(default=20_000, ge=1_000, le=100_000)

    @model_validator(mode="after")
    def validate_transport(self) -> MCPServerConfig:
        if self.transport == "streamable_http":
            if not self.url:
                raise ValueError("Streamable HTTP MCP servers require a URL")
            parsed = urlparse(self.url)
            if parsed.scheme not in {"https", "http"}:
                raise ValueError("MCP URL must use HTTP or HTTPS")
            try:
                address = ipaddress.ip_address(parsed.hostname or "")
            except ValueError:
                address = None
            if address and (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
            ) and parsed.hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("MCP URL cannot target a private or reserved network address")
            if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("Remote MCP servers must use HTTPS")
        elif not self.command:
            raise ValueError("stdio MCP servers require a command")
        return self

    def permits(self, tool_name: str) -> bool:
        return self.enabled and ("*" in self.allowed_tools or tool_name in self.allowed_tools)


class MCPAccessError(PermissionError):
    pass


def _default_client_factory(config: MCPServerConfig):
    from mcp import Client, StdioServerParameters
    from mcp.client.streamable_http import StreamableHTTPTransport

    if config.transport == "streamable_http":
        class IsolatedHTTPTransport(StreamableHTTPTransport):
            def _prepare_headers(self) -> dict[str, str]:
                return {**super()._prepare_headers(), **config.headers}

        return Client(
            IsolatedHTTPTransport(str(config.url)),
            read_timeout_seconds=config.timeout_seconds,
        )
    return Client(
        StdioServerParameters(
            command=str(config.command),
            args=config.args,
            # The SDK already starts from a restricted environment.  Only
            # explicitly configured variables are added to the child process.
            env=config.env or None,
        ),
        read_timeout_seconds=config.timeout_seconds,
    )


class MCPClientManager:
    def __init__(
        self,
        configs: list[MCPServerConfig],
        *,
        client_factory: Callable[[MCPServerConfig], Any] = _default_client_factory,
    ) -> None:
        self.configs = {item.server_id: item for item in configs}
        if len(self.configs) != len(configs):
            raise ValueError("Duplicate MCP server IDs")
        self.client_factory = client_factory
        self._catalog: dict[str, ToolDefinition] = {}

    async def discover(self, server_id: str) -> list[ToolDefinition]:
        config = self._enabled_config(server_id)
        await self._validate_resolved_target(config)
        definitions: list[ToolDefinition] = []
        async with self.client_factory(config) as client:
            cursor = None
            while True:
                response = await asyncio.wait_for(
                    client.list_tools(cursor=cursor), timeout=config.timeout_seconds
                )
                for tool in response.tools:
                    if not config.permits(tool.name):
                        continue
                    schema_size = len(
                        json.dumps(tool.input_schema or {}, ensure_ascii=False, default=str)
                    )
                    if schema_size > 64_000:
                        raise MCPAccessError(f"MCP tool schema is too large: {tool.name}")
                    canonical_name = self.canonical_name(server_id, tool.name)
                    annotations = tool.annotations.model_dump() if tool.annotations else {}
                    definition = ToolDefinition(
                        name=canonical_name,
                        description=(tool.description or tool.title or tool.name)[:4000],
                        input_schema=tool.input_schema,
                        output_schema=tool.output_schema or {},
                        source=ToolSource.MCP,
                        server_id=server_id,
                        permissions=config.permission_scopes,
                        timeout_ms=round(config.timeout_seconds * 1000),
                        idempotent=bool(annotations.get("idempotent_hint", False)),
                        metadata={
                            "remote_name": tool.name,
                            "annotations": annotations,
                            "untrusted_remote_metadata": True,
                        },
                    )
                    self._catalog[canonical_name] = definition
                    definitions.append(definition)
                cursor = response.next_cursor
                if cursor is None:
                    break
        return definitions

    def register(self, definition: ToolDefinition) -> None:
        """Hydrate a previously approved persisted definition for one isolated call."""
        if definition.source != ToolSource.MCP or not definition.server_id:
            raise MCPAccessError("Only namespaced MCP definitions can be registered")
        expected = self.configs.get(definition.server_id)
        if expected is None:
            raise MCPAccessError("MCP definition belongs to an unknown connection")
        self._catalog[definition.name] = definition

    async def call(self, call: AgentToolCall) -> AgentToolResult:
        if call.source != ToolSource.MCP or not call.server_id:
            raise MCPAccessError("MCP calls require an explicit server_id")
        config = self._enabled_config(call.server_id)
        await self._validate_resolved_target(config)
        expected_prefix = f"mcp__{call.server_id}__"
        if not call.tool_name.startswith(expected_prefix):
            raise MCPAccessError("Tool does not belong to the selected MCP connection")
        definition = self._catalog.get(call.tool_name)
        if definition is None:
            raise MCPAccessError("Tool must be discovered and approved before execution")
        if definition.server_id != call.server_id:
            raise MCPAccessError("Tool does not belong to the selected MCP connection")
        remote_name = str(definition.metadata.get("remote_name") or "")
        if not remote_name:
            raise MCPAccessError("Discovered tool is missing its remote name")
        if not config.permits(remote_name):
            raise MCPAccessError(f"Tool {remote_name} is not allowed for {call.server_id}")

        from jsonschema import ValidationError, validate

        try:
            validate(call.arguments, definition.input_schema)
        except ValidationError as exc:
            return AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.INVALID_ARGUMENTS,
                error=ToolError(
                    code="invalid_arguments",
                    message=exc.message,
                    retryable=False,
                ),
            )

        try:
            async with self.client_factory(config) as client:
                response = await asyncio.wait_for(
                    client.call_tool(remote_name, call.arguments),
                    timeout=config.timeout_seconds,
                )
        except TimeoutError:
            return AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.TIMED_OUT,
                error=ToolError(code="timeout", message="MCP tool timed out", retryable=True),
            )
        content = []
        remaining = config.max_result_chars
        truncated = False
        if response.structured_content is not None:
            encoded = json.dumps(response.structured_content, ensure_ascii=False, default=str)
            if len(encoded) <= remaining:
                content.append(JsonContentBlock(data=response.structured_content))
                remaining -= len(encoded)
            else:
                content.append(TextContentBlock(text=encoded[:remaining]))
                remaining = 0
                truncated = True
        for block in response.content:
            if remaining <= 0:
                truncated = True
                break
            if getattr(block, "type", None) == "text":
                value = str(block.text)
            else:
                value = json.dumps(
                    block.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                    default=str,
                )
            if len(value) > remaining:
                value = value[:remaining]
                truncated = True
            content.append(TextContentBlock(text=value))
            remaining -= len(value)
        if response.is_error:
            return AgentToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.FAILED,
                content=content,
                truncated=truncated,
                error=ToolError(
                    code="mcp_tool_error",
                    message="MCP server reported a tool error",
                    retryable=False,
                ),
            )
        return AgentToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            status=ToolCallStatus.SUCCESS,
            content=content,
            truncated=truncated,
        )

    def _enabled_config(self, server_id: str) -> MCPServerConfig:
        config = self.configs.get(server_id)
        if config is None:
            raise MCPAccessError(f"Unknown MCP server: {server_id}")
        if not config.enabled:
            raise MCPAccessError(f"MCP server is disabled: {server_id}")
        return config

    async def _validate_resolved_target(self, config: MCPServerConfig) -> None:
        # Test clients never open sockets. Production transport is checked on
        # every discovery/call so a hostname cannot silently move to a private target.
        if (
            self.client_factory is not _default_client_factory
            or config.transport != "streamable_http"
        ):
            return
        parsed = urlparse(str(config.url))
        hostname = parsed.hostname or ""
        if hostname in {"localhost", "127.0.0.1", "::1"}:
            return
        try:
            resolved = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                ),
                timeout=min(5.0, config.timeout_seconds),
            )
        except (OSError, TimeoutError) as exc:
            raise MCPAccessError("MCP hostname could not be resolved safely") from exc
        addresses = {item[4][0] for item in resolved}
        if not addresses:
            raise MCPAccessError("MCP hostname did not resolve to an address")
        for value in addresses:
            address = ipaddress.ip_address(value)
            if (
                address.is_private
                or address.is_loopback
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
                or address.is_unspecified
            ):
                raise MCPAccessError("MCP hostname resolves to a private or reserved address")

    @staticmethod
    def canonical_name(server_id: str, remote_name: str) -> str:
        def clean(value: str, limit: int) -> str:
            normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_") or "tool"
            if len(normalized) <= limit:
                return normalized
            import hashlib

            suffix = hashlib.sha256(value.encode()).hexdigest()[:8]
            return f"{normalized[: limit - 10]}__{suffix}"

        return f"mcp__{clean(server_id, 20)}__{clean(remote_name, 32)}"

    @staticmethod
    def remote_name(server_id: str, canonical_name: str) -> str:
        prefix = f"mcp__{server_id}__"
        if not canonical_name.startswith(prefix):
            raise MCPAccessError("Tool does not belong to the selected MCP connection")
        return canonical_name[len(prefix) :]
