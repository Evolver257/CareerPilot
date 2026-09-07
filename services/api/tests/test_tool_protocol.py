import json

from app.schemas.tool_protocol import (
    AgentToolCall,
    AgentToolResult,
    JsonContentBlock,
    ToolCallStatus,
    ToolDefinition,
    ToolError,
)
from app.services.tool_protocol import (
    anthropic_tool_result_block,
    canonical_tool_signature,
    openai_tool_result_message,
    parse_anthropic_tool_calls,
    parse_openai_tool_calls,
    to_anthropic_tools,
    to_openai_tools,
    with_idempotency_key,
)


def _definition():
    return ToolDefinition(
        name="search_jobs",
        description="Search the authorized job inventory",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )


def test_provider_tool_definitions_preserve_json_schema():
    definition = _definition()
    openai = to_openai_tools([definition])[0]
    anthropic = to_anthropic_tools([definition])[0]

    assert openai["type"] == "function"
    assert openai["function"]["parameters"] == definition.input_schema
    assert anthropic["input_schema"] == definition.input_schema


def test_parse_native_openai_and_anthropic_tool_calls():
    openai = parse_openai_tool_calls(
        {
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search_jobs", "arguments": '{"query":"RAG"}'},
                }
            ]
        }
    )
    anthropic = parse_anthropic_tool_calls(
        {
            "content": [
                {
                    "type": "tool_use",
                    "id": "call-2",
                    "name": "search_jobs",
                    "input": {"query": "RAG"},
                }
            ]
        }
    )

    assert openai[0].arguments == {"query": "RAG"}
    assert anthropic[0].arguments == {"query": "RAG"}


def test_idempotency_is_stable_across_argument_order():
    left = canonical_tool_signature("tool", {"a": 1, "b": [2]})
    right = canonical_tool_signature("tool", {"b": [2], "a": 1})
    assert left == right
    call = with_idempotency_key(
        AgentToolCall(call_id="c", tool_name="tool", arguments={"a": 1}), run_id="r"
    )
    assert call.idempotency_key.startswith("r:")


def test_provider_result_messages_keep_status_content_and_errors():
    result = AgentToolResult(
        call_id="call-1",
        tool_name="search_jobs",
        status=ToolCallStatus.FAILED,
        content=[JsonContentBlock(data={"partial": True})],
        error=ToolError(code="timeout", message="Timed out", retryable=True),
    )
    openai = openai_tool_result_message(result)
    anthropic = anthropic_tool_result_block(result)

    assert openai["role"] == "tool"
    assert json.loads(openai["content"])["status"] == "FAILED"
    assert anthropic["type"] == "tool_result"
    assert anthropic["is_error"] is True
