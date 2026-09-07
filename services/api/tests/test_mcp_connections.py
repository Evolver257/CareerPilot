from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.base import Base
from app.models.entities import MCPConnection, MCPDiscoveredTool, User
from app.services.mcp_connections import MCPConnectionService


async def test_mcp_connection_is_disabled_encrypted_and_isolated_from_response(client) -> None:
    response = await client.post(
        "/api/mcp/connections",
        json={
            "name": "测试知识服务",
            "namespace": "test_kb",
            "transport": "streamable_http",
            "endpoint": "https://mcp.example.com/service",
            "credentials": {"Authorization": "Bearer secret-token"},
            "permission_scopes": ["knowledge.read"],
            "allowed_tools": ["search"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["enabled"] is False
    assert body["credentials_configured"] is True
    assert "secret-token" not in str(body)

    listed = await client.get("/api/mcp/connections")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "secret-token" not in listed.text


async def test_mcp_rejects_private_endpoint_and_unknown_permission(client) -> None:
    private = await client.post(
        "/api/mcp/connections",
        json={
            "name": "private",
            "namespace": "private",
            "transport": "streamable_http",
            "endpoint": "https://10.0.0.2/mcp",
        },
    )
    assert private.status_code == 422

    permission = await client.post(
        "/api/mcp/connections",
        json={
            "name": "bad scope",
            "namespace": "bad_scope",
            "transport": "streamable_http",
            "endpoint": "https://mcp.example.com/service",
            "permission_scopes": ["root.all"],
        },
    )
    assert permission.status_code == 422


async def test_stdio_requires_operator_command_allowlist(client) -> None:
    response = await client.post(
        "/api/mcp/connections",
        json={
            "name": "unsafe",
            "namespace": "unsafe",
            "transport": "stdio",
            "command": "powershell.exe",
        },
    )
    assert response.status_code == 422
    assert "白名单" in response.json()["detail"]


async def test_http_credentials_cannot_override_transport_headers(client) -> None:
    response = await client.post(
        "/api/mcp/connections",
        json={
            "name": "unsafe headers",
            "namespace": "unsafe_headers",
            "transport": "streamable_http",
            "endpoint": "https://mcp.example.com/service",
            "credentials": {"Host": "attacker.example"},
        },
    )
    assert response.status_code == 422
    assert "受保护" in response.json()["detail"]


async def test_advisor_exposes_only_enabled_allowlisted_read_only_tools() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with factory() as session:
            settings = get_settings()
            user = User(email=settings.default_user_email, name="Test")
            read_connection = MCPConnection(
                user=user,
                name="Read",
                namespace="read_kb",
                transport="streamable_http",
                endpoint="https://mcp.example.test/service",
                enabled=True,
                permission_scopes=["knowledge.read"],
                allowed_tools=["search"],
            )
            read_connection.discovered_tools.append(
                MCPDiscoveredTool(
                    remote_name="search",
                    canonical_name="legacy-name",
                    description="Search external knowledge",
                    input_schema={"type": "object", "properties": {}},
                    output_schema={},
                    schema_hash="a" * 64,
                    active=True,
                )
            )
            write_connection = MCPConnection(
                user=user,
                name="Write",
                namespace="write_kb",
                transport="streamable_http",
                endpoint="https://mcp.example.test/service",
                enabled=True,
                permission_scopes=["external.write"],
                allowed_tools=["mutate"],
            )
            write_connection.discovered_tools.append(
                MCPDiscoveredTool(
                    remote_name="mutate",
                    canonical_name="legacy-write",
                    description="Mutate data",
                    input_schema={"type": "object", "properties": {}},
                    output_schema={},
                    schema_hash="b" * 64,
                    active=True,
                )
            )
            session.add_all([read_connection, write_connection])
            await session.commit()

            definitions = await MCPConnectionService(session).advisor_definitions()

            assert [item.name for item in definitions] == ["mcp__read_kb__search"]
            assert definitions[0].permissions == ["knowledge.read"]
            assert definitions[0].metadata["untrusted_remote_metadata"] is True
    finally:
        await engine.dispose()
