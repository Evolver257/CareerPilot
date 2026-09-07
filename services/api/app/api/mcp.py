from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.dependencies import get_mcp_connection_service
from app.models.entities import MCPConnection, MCPDiscoveredTool
from app.schemas.mcp import (
    MCPConnectionCreate,
    MCPConnectionRead,
    MCPConnectionUpdate,
    MCPDiscoveryRead,
    MCPToolRead,
)
from app.services.mcp_connections import MCPConnectionError, MCPConnectionService

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


def _connection_read(item: MCPConnection) -> MCPConnectionRead:
    return MCPConnectionRead(
        id=item.id,
        name=item.name,
        namespace=item.namespace,
        transport=item.transport,
        endpoint=item.endpoint,
        command=item.command,
        arguments=item.arguments,
        credentials_configured=bool(item.encrypted_credentials),
        credentials_hint=item.credentials_hint,
        enabled=item.enabled,
        status=item.status,
        permission_scopes=item.permission_scopes,
        allowed_tools=item.allowed_tools,
        blocked_tools=item.blocked_tools,
        connect_timeout=item.connect_timeout,
        tool_timeout=item.tool_timeout,
        last_health_check=item.last_health_check,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _tool_read(item: MCPDiscoveredTool) -> MCPToolRead:
    return MCPToolRead(
        id=item.id,
        remote_name=item.remote_name,
        canonical_name=item.canonical_name,
        description=item.description,
        input_schema=item.input_schema,
        output_schema=item.output_schema,
        schema_hash=item.schema_hash,
        active=item.active,
        last_seen_at=item.last_seen_at,
    )


def _error(exc: MCPConnectionError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/connections", response_model=list[MCPConnectionRead])
async def list_connections(
    service: MCPConnectionService = Depends(get_mcp_connection_service),
) -> list[MCPConnectionRead]:
    return [_connection_read(item) for item in await service.list()]


@router.post(
    "/connections", response_model=MCPConnectionRead, status_code=status.HTTP_201_CREATED
)
async def create_connection(
    payload: MCPConnectionCreate,
    service: MCPConnectionService = Depends(get_mcp_connection_service),
) -> MCPConnectionRead:
    try:
        return _connection_read(await service.create(payload))
    except MCPConnectionError as exc:
        raise _error(exc) from exc


@router.patch("/connections/{connection_id}", response_model=MCPConnectionRead)
async def update_connection(
    connection_id: UUID,
    payload: MCPConnectionUpdate,
    service: MCPConnectionService = Depends(get_mcp_connection_service),
) -> MCPConnectionRead:
    try:
        return _connection_read(await service.update(connection_id, payload))
    except MCPConnectionError as exc:
        raise _error(exc) from exc


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    service: MCPConnectionService = Depends(get_mcp_connection_service),
) -> Response:
    try:
        await service.delete(connection_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except MCPConnectionError as exc:
        raise _error(exc) from exc


@router.post("/connections/{connection_id}/discover", response_model=MCPDiscoveryRead)
async def discover_connection_tools(
    connection_id: UUID,
    service: MCPConnectionService = Depends(get_mcp_connection_service),
) -> MCPDiscoveryRead:
    try:
        connection, changed = await service.discover(connection_id)
        return MCPDiscoveryRead(
            connection=_connection_read(connection),
            tools=[_tool_read(item) for item in connection.discovered_tools],
            changed=changed,
        )
    except MCPConnectionError as exc:
        raise _error(exc) from exc


@router.get("/connections/{connection_id}/tools", response_model=list[MCPToolRead])
async def list_connection_tools(
    connection_id: UUID,
    service: MCPConnectionService = Depends(get_mcp_connection_service),
) -> list[MCPToolRead]:
    try:
        connection = await service.get(connection_id)
        return [_tool_read(item) for item in connection.discovered_tools]
    except MCPConnectionError as exc:
        raise _error(exc) from exc
