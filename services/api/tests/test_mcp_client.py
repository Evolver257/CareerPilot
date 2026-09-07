import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.schemas.tool_protocol import AgentToolCall, ToolCallStatus, ToolSource
from app.services.mcp_client import MCPAccessError, MCPClientManager, MCPServerConfig


class _Annotations(BaseModel):
    idempotent_hint: bool = True


class _TextBlock(BaseModel):
    type: str = "text"
    text: str


class _FakeClient:
    def __init__(self, config):
        self.config = config

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def list_tools(self, *, cursor=None):
        assert cursor is None
        tools = [
            SimpleNamespace(
                name="search",
                title="Search",
                description="Search approved data",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                output_schema={"type": "object"},
                annotations=_Annotations(),
            ),
            SimpleNamespace(
                name="delete_all",
                title="Delete",
                description="Not allowlisted",
                input_schema={"type": "object"},
                output_schema=None,
                annotations=None,
            ),
        ]
        return SimpleNamespace(tools=tools, next_cursor=None)

    async def call_tool(self, name, arguments):
        assert name == "search"
        return SimpleNamespace(
            structured_content={"query": arguments["query"], "count": 1},
            content=[_TextBlock(text="one result")],
            is_error=False,
        )


class _LargeResultClient(_FakeClient):
    async def call_tool(self, name, arguments):
        assert name == "search"
        return SimpleNamespace(
            structured_content=None,
            content=[_TextBlock(text="x" * 2_000)],
            is_error=False,
        )


def _config(**updates):
    values = {
        "server_id": "jobs",
        "transport": "streamable_http",
        "url": "https://mcp.example.test/mcp",
        "enabled": True,
        "allowed_tools": ["search"],
        "permission_scopes": ["jobs:read"],
    }
    values.update(updates)
    return MCPServerConfig(**values)


async def test_mcp_discovery_is_allowlisted_namespaced_and_callable():
    manager = MCPClientManager([_config()], client_factory=_FakeClient)
    definitions = await manager.discover("jobs")

    assert [item.name for item in definitions] == ["mcp__jobs__search"]
    assert definitions[0].permissions == ["jobs:read"]
    assert definitions[0].metadata["untrusted_remote_metadata"] is True

    result = await manager.call(
        AgentToolCall(
            call_id="call-1",
            tool_name="mcp__jobs__search",
            arguments={"query": "RAG"},
            source=ToolSource.MCP,
            server_id="jobs",
        )
    )
    assert result.status == ToolCallStatus.SUCCESS
    assert result.content[0].data["count"] == 1


async def test_mcp_rejects_undiscovered_invalid_and_cross_connection_calls():
    manager = MCPClientManager([_config()], client_factory=_FakeClient)
    call = AgentToolCall(
        call_id="call-1",
        tool_name="mcp__jobs__search",
        arguments={},
        source=ToolSource.MCP,
        server_id="jobs",
    )
    with pytest.raises(MCPAccessError, match="discovered"):
        await manager.call(call)
    await manager.discover("jobs")
    result = await manager.call(call)
    assert result.status == ToolCallStatus.INVALID_ARGUMENTS
    assert result.error.code == "invalid_arguments"

    with pytest.raises(MCPAccessError, match="belong"):
        await manager.call(call.model_copy(update={"tool_name": "mcp__other__search"}))


def test_mcp_config_is_disabled_by_default_and_requires_tls_for_remote_hosts():
    with pytest.raises(ValueError, match="HTTPS"):
        MCPServerConfig(
            server_id="bad",
            transport="streamable_http",
            url="http://example.com/mcp",
        )
    manager = MCPClientManager(
        [_config(enabled=False)],
        client_factory=_FakeClient,
    )
    with pytest.raises(MCPAccessError, match="disabled"):
        manager._enabled_config("jobs")


def test_connection_credentials_are_scoped_to_one_config():
    first = _config(
        server_id="first",
        headers={"Authorization": "Bearer one"},
    )
    second = _config(
        server_id="second",
        headers={"Authorization": "Bearer two"},
    )
    assert first.headers["Authorization"] == "Bearer one"
    assert second.headers["Authorization"] == "Bearer two"


async def test_mcp_result_is_bounded_and_marked_truncated():
    manager = MCPClientManager(
        [_config(max_result_chars=1_000)], client_factory=_LargeResultClient
    )
    await manager.discover("jobs")
    result = await manager.call(
        AgentToolCall(
            call_id="large-call",
            tool_name="mcp__jobs__search",
            arguments={"query": "RAG"},
            source=ToolSource.MCP,
            server_id="jobs",
        )
    )
    assert result.status == ToolCallStatus.SUCCESS
    assert result.truncated is True
    assert len(result.content[0].text) == 1_000


async def test_production_mcp_dns_resolution_rejects_private_targets(monkeypatch):
    manager = MCPClientManager([_config()])

    async def private_result(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", private_result)
    with pytest.raises(MCPAccessError, match="private or reserved"):
        await manager._validate_resolved_target(manager.configs["jobs"])
