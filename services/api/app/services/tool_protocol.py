"""Adapters between provider payloads and CareerPilot's neutral tool protocol."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from app.schemas.tool_protocol import (
    AgentToolCall,
    AgentToolResult,
    ToolDefinition,
    ToolSource,
)


def canonical_tool_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(
        {"tool_name": tool_name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def with_idempotency_key(call: AgentToolCall, *, run_id: str) -> AgentToolCall:
    if call.idempotency_key:
        return call
    signature = canonical_tool_signature(call.tool_name, call.arguments)
    return call.model_copy(update={"idempotency_key": f"{run_id}:{signature}"})


def to_openai_tools(definitions: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": item.name,
                "description": item.description,
                "parameters": item.input_schema,
            },
        }
        for item in definitions
        if item.enabled
    ]


def to_anthropic_tools(definitions: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "description": item.description,
            "input_schema": item.input_schema,
        }
        for item in definitions
        if item.enabled
    ]


def parse_openai_tool_calls(message: dict[str, Any]) -> list[AgentToolCall]:
    result = []
    for raw in message.get("tool_calls") or []:
        if not isinstance(raw, dict) or raw.get("type") != "function":
            continue
        function = raw.get("function") or {}
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("OpenAI tool arguments must decode to an object")
        result.append(
            AgentToolCall(
                call_id=str(raw.get("id") or uuid4()),
                tool_name=str(function.get("name") or ""),
                arguments=arguments,
                source=ToolSource.LOCAL,
                metadata={"provider": "openai"},
            )
        )
    return result


def parse_anthropic_tool_calls(message: dict[str, Any]) -> list[AgentToolCall]:
    result = []
    for block in message.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        arguments = block.get("input") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Anthropic tool input must be an object")
        result.append(
            AgentToolCall(
                call_id=str(block.get("id") or uuid4()),
                tool_name=str(block.get("name") or ""),
                arguments=arguments,
                source=ToolSource.LOCAL,
                metadata={"provider": "anthropic"},
            )
        )
    return result


def openai_tool_result_message(result: AgentToolResult) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": result.call_id,
        "content": json.dumps(
            {
                "status": result.status.value,
                "content": [item.model_dump(mode="json") for item in result.content],
                "error": result.error.model_dump(mode="json") if result.error else None,
            },
            ensure_ascii=False,
        ),
    }


def anthropic_tool_result_block(result: AgentToolResult) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": result.call_id,
        "is_error": result.error is not None,
        "content": json.dumps(
            {
                "status": result.status.value,
                "content": [item.model_dump(mode="json") for item in result.content],
                "error": result.error.model_dump(mode="json") if result.error else None,
            },
            ensure_ascii=False,
        ),
    }


def definition_from_manifest(manifest, input_schema: dict[str, Any], output_schema: dict[str, Any]):
    """Bridge existing stable AgentTool manifests without changing their API."""

    return ToolDefinition(
        name=manifest.name,
        description=manifest.description,
        input_schema=input_schema,
        output_schema=output_schema,
        risk_level=manifest.risk_level.value,
        permissions=list(manifest.tags),
        idempotent=not manifest.requires_confirmation,
        metadata={
            "capabilities": list(manifest.capabilities),
            "preconditions": list(manifest.preconditions),
            "postconditions": list(manifest.postconditions),
            "cost_level": manifest.cost_level,
            "latency_level": manifest.latency_level,
        },
    )
