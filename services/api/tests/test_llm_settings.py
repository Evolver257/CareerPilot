import json

import httpx
import pytest
from pydantic import BaseModel

from app.llm.provider import (
    AnthropicProvider,
    LLMProviderError,
    MockLLMProvider,
    OpenAIProvider,
)
from app.schemas.llm import LLMConnectionTestRead
from app.schemas.tool_protocol import (
    AgentMessage,
    AgentToolCall,
    AgentToolResult,
    JsonContentBlock,
    ToolCallStatus,
    ToolDefinition,
)
from app.services.llm_settings import LLMSettingsService


async def test_llm_settings_are_encrypted_switchable_and_redacted(client) -> None:
    initial = await client.get("/api/llm/settings")
    assert initial.status_code == 200
    assert initial.json() == {"active_provider": "mock", "providers": []}

    saved = await client.put(
        "/api/llm/providers/openai",
        json={
            "api_key": "sk-test-openai-key-1234",
            "model": "gpt-test",
            "base_url": "https://example.com/v1",
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["active_provider"] == "openai"
    openai = next(item for item in payload["providers"] if item["provider"] == "openai")
    assert openai["api_key_hint"].endswith("1234")
    assert "api_key" not in openai
    assert "encrypted" not in json.dumps(openai).lower()

    anthropic = await client.put(
        "/api/llm/providers/anthropic",
        json={"api_key": "sk-ant-test-key-5678", "model": "claude-test"},
    )
    assert anthropic.status_code == 200
    assert anthropic.json()["active_provider"] == "anthropic"

    selected = await client.put("/api/llm/active", json={"provider": "openai"})
    assert selected.status_code == 200
    assert selected.json()["active_provider"] == "openai"

    deleted = await client.delete("/api/llm/providers/anthropic")
    assert deleted.status_code == 204
    remaining = await client.get("/api/llm/settings")
    assert [item["provider"] for item in remaining.json()["providers"]] == ["openai"]

    mock = await client.put("/api/llm/active", json={"provider": "mock"})
    assert mock.status_code == 200
    assert mock.json()["active_provider"] == "mock"

    mock_again = await client.get("/api/llm/settings")
    assert mock_again.json()["active_provider"] == "mock"


async def test_llm_connection_test_does_not_persist_configuration(monkeypatch, client) -> None:
    received: dict[str, str] = {}

    async def fake_test_connection(
        _service: LLMSettingsService,
        provider: str,
        *,
        api_key: str,
        model: str,
        base_url: str,
    ) -> LLMConnectionTestRead:
        received.update(provider=provider, api_key=api_key, model=model, base_url=base_url)
        return LLMConnectionTestRead(
            provider="openai", model=model, latency_ms=12.3, message="连接成功，未修改已保存配置"
        )

    monkeypatch.setattr(LLMSettingsService, "test_connection", fake_test_connection)
    response = await client.post(
        "/api/llm/test",
        json={
            "provider": "openai",
            "api_key": "sk-validation-key-1234",
            "model": "gpt-test",
            "base_url": "https://example.invalid/v1",
        },
    )
    assert response.status_code == 200
    assert response.json()["latency_ms"] == 12.3
    assert received == {
        "provider": "openai",
        "api_key": "sk-validation-key-1234",
        "model": "gpt-test",
        "base_url": "https://example.invalid/v1",
    }
    settings = await client.get("/api/llm/settings")
    assert settings.json() == {"active_provider": "mock", "providers": []}


async def test_openai_provider_uses_chat_completions_format() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    provider = OpenAIProvider(
        api_key="sk-test-openai-key",
        model="gpt-test",
        base_url="https://proxy.example/v1",
        transport=httpx.MockTransport(handler),
    )
    assert await provider.generate("say hello") == "hello"
    assert requests[0].url.path == "/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer sk-test-openai-key"
    assert json.loads(requests[0].content)["messages"][0]["content"] == "say hello"
    assert provider.last_usage is not None
    assert provider.last_usage.total_tokens == 5


async def test_openai_provider_uses_native_function_calling() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_jobs",
                                        "arguments": '{"query":"RAG"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3},
            },
        )

    provider = OpenAIProvider(
        api_key="sk-test",
        model="gpt-test",
        base_url="https://proxy.example/v1",
        transport=httpx.MockTransport(handler),
    )
    previous_call = AgentToolCall(
        call_id="previous-call",
        tool_name="search_jobs",
        arguments={"query": "Python"},
    )
    result = await provider.decide_with_tools(
        "choose",
        [
            ToolDefinition(
                name="search_jobs",
                description="Search jobs",
                input_schema={"type": "object"},
            )
        ],
        messages=[
            AgentMessage(role="user", content="find a job"),
            AgentMessage(role="assistant", tool_calls=[previous_call]),
            AgentMessage(
                role="tool",
                tool_result=AgentToolResult(
                    call_id="previous-call",
                    tool_name="search_jobs",
                    status=ToolCallStatus.SUCCESS,
                    content=[JsonContentBlock(data={"count": 2})],
                ),
            ),
        ],
    )

    body = json.loads(requests[0].content)
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is False
    assert body["tools"][0]["function"]["name"] == "search_jobs"
    assert [item["role"] for item in body["messages"]] == [
        "user",
        "assistant",
        "tool",
    ]
    assert body["messages"][2]["tool_call_id"] == "previous-call"
    assert result.tool_calls[0].arguments == {"query": "RAG"}
    assert result.stop_reason == "tool_calls"


async def test_openai_provider_can_use_embeddings_endpoint() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2, 0.3]}], "usage": {"prompt_tokens": 4}},
        )

    provider = OpenAIProvider(
        api_key="sk-test-openai-key",
        model="gpt-test",
        embedding_model="text-embedding-3-small",
        dimensions=3,
        base_url="https://proxy.example/v1",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed("RAG 后端开发") == [0.1, 0.2, 0.3]
    assert requests[0].url.path == "/v1/embeddings"
    body = json.loads(requests[0].content)
    assert body == {
        "model": "text-embedding-3-small",
        "input": ["RAG 后端开发"],
        "dimensions": 3,
    }


async def test_openai_provider_batches_embedding_inputs_and_restores_index_order() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["input"] == ["first", "second"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ]
            },
        )

    provider = OpenAIProvider(
        api_key="sk-test-openai-key",
        embedding_model="text-embedding-3-small",
        dimensions=3,
        base_url="https://proxy.example/v1",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.embed_many(["first", "second"]) == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]


async def test_local_embedding_preserves_chinese_phrase_overlap() -> None:
    provider = MockLLMProvider(dimensions=384)
    first = await provider.embed("检索增强生成与后端服务开发")
    second = await provider.embed("RAG 后端开发")
    cosine = sum(left * right for left, right in zip(first, second, strict=True))

    assert cosine > 0.1


async def test_anthropic_provider_uses_messages_format_and_structured_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["messages"][0]["content"].startswith("return data"):
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": '{"score": 92}'}],
                    "usage": {"input_tokens": 4, "output_tokens": 3},
                },
            )
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    class Score(BaseModel):
        score: int

    provider = AnthropicProvider(
        api_key="sk-ant-test-key",
        model="claude-test",
        base_url="https://proxy.example",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate_structured("return data", Score)
    assert result.score == 92


async def test_anthropic_provider_uses_native_tool_use_blocks() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu-1",
                        "name": "search_jobs",
                        "input": {"query": "Agent"},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        )

    provider = AnthropicProvider(
        api_key="sk-ant-test",
        model="claude-test",
        base_url="https://proxy.example",
        transport=httpx.MockTransport(handler),
    )
    previous_call = AgentToolCall(
        call_id="previous-tool",
        tool_name="search_jobs",
        arguments={"query": "Python"},
    )
    result = await provider.decide_with_tools(
        "choose",
        [
            ToolDefinition(
                name="search_jobs",
                description="Search jobs",
                input_schema={"type": "object"},
            )
        ],
        messages=[
            AgentMessage(role="user", content="find a job"),
            AgentMessage(role="assistant", tool_calls=[previous_call]),
            AgentMessage(
                role="tool",
                tool_result=AgentToolResult(
                    call_id="previous-tool",
                    tool_name="search_jobs",
                    status=ToolCallStatus.SUCCESS,
                    content=[JsonContentBlock(data={"count": 2})],
                ),
            ),
        ],
    )

    body = json.loads(requests[0].content)
    assert body["tools"][0]["input_schema"] == {"type": "object"}
    assert "tool_choice" not in body
    assert [item["role"] for item in body["messages"]] == [
        "user",
        "assistant",
        "user",
    ]
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert result.tool_calls[0].arguments == {"query": "Agent"}
    assert result.stop_reason == "tool_use"


async def test_deepseek_anthropic_structured_call_can_disable_reasoning() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"score": 93}'}],
                "usage": {"input_tokens": 4, "output_tokens": 3},
            },
        )

    class Score(BaseModel):
        score: int

    provider = AnthropicProvider(
        api_key="sk-ant-test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/anthropic",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate_structured(
        "return data",
        Score,
        max_tokens=500,
        reasoning_effort="none",
    )

    assert result.score == 93
    payload = json.loads(requests[0].content)
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["thinking"] == {"type": "disabled"}


async def test_deepseek_anthropic_stream_yields_text_deltas_and_usage() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        events = [
            {
                "type": "message_start",
                "message": {"usage": {"input_tokens": 11}},
            },
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "第一段"},
            },
            {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "第二段"},
            },
            {"type": "message_delta", "usage": {"output_tokens": 7}},
        ]
        content = "".join(f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=content,
        )

    provider = AnthropicProvider(
        api_key="sk-ant-test-key",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/anthropic",
        transport=httpx.MockTransport(handler),
    )

    chunks = [
        chunk
        async for chunk in provider.stream(
            "stream answer",
            max_tokens=500,
            reasoning_effort="none",
        )
    ]

    assert chunks == ["第一段", "第二段"]
    payload = json.loads(requests[0].content)
    assert payload["stream"] is True
    assert payload["thinking"] == {"type": "disabled"}
    assert provider.last_usage is not None
    assert provider.last_usage.prompt_tokens == 11
    assert provider.last_usage.completion_tokens == 7


async def test_openai_stream_yields_chat_completion_deltas() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        events = [
            {"choices": [{"delta": {"content": "hello "}}]},
            {"choices": [{"delta": {"content": "world"}}]},
        ]
        content = "".join(f"data: {json.dumps(item)}\n\n" for item in events)
        content += "data: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=content,
        )

    provider = OpenAIProvider(
        api_key="sk-test-key",
        model="gpt-test",
        base_url="https://example.com/v1",
        transport=httpx.MockTransport(handler),
    )

    chunks = [chunk async for chunk in provider.stream("stream answer")]

    assert chunks == ["hello ", "world"]
    assert provider.last_usage is not None
    assert provider.last_usage.completion_tokens > 0


async def test_anthropic_structured_output_retries_thinking_only_max_tokens_response() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "private reasoning",
                            "signature": "redacted-test-signature",
                        }
                    ],
                    "stop_reason": "max_tokens",
                    "usage": {"input_tokens": 4, "output_tokens": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"score": 91}'}],
                "usage": {"input_tokens": 4, "output_tokens": 3},
            },
        )

    class Score(BaseModel):
        score: int

    provider = AnthropicProvider(
        api_key="sk-ant-test-key",
        model="deepseek-test",
        base_url="https://proxy.example",
        structured_max_tokens=2,
        structured_retry_max_tokens=4,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.generate_structured("return data", Score)

    assert result.score == 91
    assert [json.loads(request.content)["max_tokens"] for request in requests] == [2, 4]


async def test_structured_output_token_override_uses_one_bounded_attempt() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "thinking", "thinking": "private"}],
                "stop_reason": "max_tokens",
            },
        )

    class Score(BaseModel):
        score: int

    provider = AnthropicProvider(
        api_key="sk-ant-test-key",
        model="deepseek-test",
        base_url="https://proxy.example",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMProviderError):
        await provider.generate_structured("return data", Score, max_tokens=1200)

    assert len(requests) == 1
    assert json.loads(requests[0].content)["max_tokens"] == 1200
