import json

import httpx
from pydantic import BaseModel

from app.llm.provider import AnthropicProvider, OpenAIProvider
from app.schemas.llm import LLMConnectionTestRead
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
