"""Adapters between provider payloads and CareerPilot's neutral tool protocol."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from app.schemas.tool_protocol import (
    AgentMessage,
    AgentToolCall,
    AgentToolResult,
    ToolDefinition,
    ToolSource,
)


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item.text
            for item in content
            if hasattr(item, "text") and isinstance(item.text, str)
        )
    return ""


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


def to_openai_messages(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    """Serialize neutral Agent messages into OpenAI chat/tool messages."""

    result: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool" and message.tool_result is not None:
            result.append(openai_tool_result_message(message.tool_result))
            continue
        item: dict[str, Any] = {
            "role": message.role,
            "content": _message_text(message.content),
        }
        if message.role == "assistant" and message.tool_calls:
            item["content"] = item["content"] or None
            item["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.tool_name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        result.append(item)
    return result


def to_anthropic_messages(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    """Serialize neutral Agent messages into Anthropic tool-use messages."""

    result: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            # CareerAdvisor currently keeps runtime instructions in the first
            # user message. A provider-level system field can be added later.
            result.append({"role": "user", "content": _message_text(message.content)})
            continue
        if message.role == "tool" and message.tool_result is not None:
            result.append(
                {
                    "role": "user",
                    "content": [anthropic_tool_result_block(message.tool_result)],
                }
            )
            continue
        if message.role == "assistant" and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            text = _message_text(message.content)
            if text:
                blocks.append({"type": "text", "text": text})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call.call_id,
                    "name": call.tool_name,
                    "input": call.arguments,
                }
                for call in message.tool_calls
            )
            result.append({"role": "assistant", "content": blocks})
            continue
        result.append({"role": message.role, "content": _message_text(message.content)})
    return result


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
