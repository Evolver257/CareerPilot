from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel

from app.llm.usage import UsageRecord, estimate_tokens

SchemaT = TypeVar("SchemaT", bound=BaseModel)

DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
}
DEFAULT_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
}
DEFAULT_EMBEDDING_MODEL = "mock-hash-384-v2"
MOCK_EMBEDDING_VERSION = "mock-hash-384-v2"
DEFAULT_STRUCTURED_MAX_TOKENS = 8192
DEFAULT_STRUCTURED_RETRY_MAX_TOKENS = 12288


class LLMProviderError(RuntimeError):
    """Raised when a configured remote provider cannot complete a request."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str: ...

    async def generate_structured(
        self,
        prompt: str,
        schema: type[SchemaT],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> SchemaT: ...

    async def embed(self, text: str, *, model: str | None = None) -> list[float]: ...


class MockLLMProvider:
    """Deterministic local provider for development and tests without API keys."""

    provider_name = "mock"
    model = DEFAULT_EMBEDDING_MODEL
    embedding_provider_name = "mock"
    embedding_model = DEFAULT_EMBEDDING_MODEL
    embedding_version = MOCK_EMBEDDING_VERSION
    embedding_signature = MOCK_EMBEDDING_VERSION

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions
        self.embedding_signature = f"{MOCK_EMBEDDING_VERSION}:{dimensions}"
        self.last_usage: UsageRecord | None = None

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.last_usage = UsageRecord(
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(prompt),
            source="mock_estimated",
        )
        return prompt

    async def generate_structured(
        self,
        prompt: str,
        schema: type[SchemaT],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> SchemaT:
        result = schema.model_validate({})
        self.last_usage = UsageRecord(
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(result.model_dump_json()),
            source="mock_estimated",
        )
        return result

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        self.last_usage = None
        return self._hash_embedding(text)

    def _hash_embedding(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        tokens: Sequence[str] = _embedding_features(text)
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            # Non-negative feature hashing avoids unrelated terms cancelling
            # each other out, which made the previous cosine score collapse to 0.
            values[index] += 1.0 + digest[4] / 255.0 * 0.25

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return values
        return [value / norm for value in values]


class RemoteLLMProvider:
    """Shared HTTP and structured-output behavior for remote providers."""

    provider_name = "remote"

    def __init__(
        self,
        *,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        dimensions: int = 384,
        embedding_model: str | None = None,
        structured_max_tokens: int = DEFAULT_STRUCTURED_MAX_TOKENS,
        structured_retry_max_tokens: int = DEFAULT_STRUCTURED_RETRY_MAX_TOKENS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model or DEFAULT_PROVIDER_MODELS[self.provider_name]
        self.base_url = (base_url or DEFAULT_PROVIDER_BASE_URLS[self.provider_name]).rstrip("/")
        self.dimensions = dimensions
        self.embedding_model = embedding_model or DEFAULT_EMBEDDING_MODEL
        self.embedding_provider_name = self.provider_name
        self.embedding_version = (
            f"{self.embedding_provider_name}:{self.embedding_model}:{self.dimensions}:v1"
            if not self.embedding_model.startswith("mock-")
            else MOCK_EMBEDDING_VERSION
        )
        self.structured_max_tokens = max(1, structured_max_tokens)
        self.structured_retry_max_tokens = max(
            self.structured_max_tokens, structured_retry_max_tokens
        )
        self._transport = transport
        self.last_usage: UsageRecord | None = None
        self._embedding_fallback = MockLLMProvider(dimensions=dimensions)

    @property
    def embedding_signature(self) -> str:
        if self.provider_name == "openai" and not self.embedding_model.startswith("mock-"):
            return self.embedding_version
        return self._embedding_fallback.embedding_signature

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        data = await self._generate_payload(prompt, model=model, max_tokens=max_tokens)
        self._record_usage(data)
        text = self._extract_text(data)
        if not text:
            stop_reason = data.get("stop_reason")
            content_types = _response_content_types(data)
            diagnostics = []
            if stop_reason:
                diagnostics.append(f"stop_reason={stop_reason}")
            if content_types:
                diagnostics.append("content_types=" + ",".join(content_types))
            suffix = f" ({'; '.join(diagnostics)})" if diagnostics else ""
            raise LLMProviderError(
                f"{self.provider_name} returned an empty response{suffix}",
                retryable=stop_reason == "max_tokens" or "thinking" in content_types,
            )
        return text

    async def generate_structured(
        self,
        prompt: str,
        schema: type[SchemaT],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> SchemaT:
        schema_prompt = (
            f"{prompt}\n\nReturn JSON only. Do not wrap it in Markdown fences. "
            "The JSON must follow this schema:\n"
            f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        last_error: LLMProviderError | None = None
        token_limits = (
            (max(1, max_tokens),)
            if max_tokens is not None
            else (self.structured_max_tokens, self.structured_retry_max_tokens)
        )
        for attempt, token_limit in enumerate(token_limits):
            try:
                raw = await self.generate(
                    schema_prompt,
                    model=model,
                    max_tokens=token_limit,
                )
                parsed = _parse_json_object(raw)
                return schema.model_validate(parsed)
            except LLMProviderError as exc:
                last_error = exc
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                last_error = LLMProviderError(
                    f"{self.provider_name} returned invalid structured output",
                    retryable=True,
                )
                last_error.__cause__ = exc

            if attempt < len(token_limits) - 1 and last_error is not None and last_error.retryable:
                continue
            raise last_error
        raise last_error or LLMProviderError(
            f"{self.provider_name} returned invalid structured output"
        )

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        if self.provider_name == "openai" and not self.embedding_model.startswith("mock-"):
            return await self._embed_openai(text)

        # Anthropic-compatible endpoints do not expose the OpenAI embeddings
        # contract. Keep a deterministic local fallback for those providers.
        self.last_usage = None
        return await self._embedding_fallback.embed(text, model=model)

    async def _embed_openai(self, text: str) -> list[float]:
        base_url = self.base_url
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        payload: dict[str, object] = {
            "model": self.embedding_model,
            "input": text,
        }
        # text-embedding-3-* supports dimension shortening. Keeping the
        # persisted dimension configurable lets existing pgvector schemas stay
        # usable while users opt into a real embedding model.
        if self.embedding_model.startswith("text-embedding-3-"):
            payload["dimensions"] = self.dimensions
        data = await self._post_json(
            f"{base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )
        items = data.get("data") or []
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise LLMProviderError("openai returned an invalid embedding payload")
        raw_embedding = items[0].get("embedding")
        if not isinstance(raw_embedding, list) or not all(
            isinstance(value, int | float) for value in raw_embedding
        ):
            raise LLMProviderError("openai returned an invalid embedding vector")
        embedding = [float(value) for value in raw_embedding]
        if len(embedding) != self.dimensions:
            raise LLMProviderError(
                "openai embedding dimension mismatch: "
                f"expected {self.dimensions}, got {len(embedding)}"
            )
        usage = data.get("usage") or {}
        self.last_usage = UsageRecord(
            prompt_tokens=int(usage.get("prompt_tokens", usage.get("total_tokens", 0)) or 0),
            completion_tokens=0,
            source="openai_embedding",
        )
        return embedding

    async def _generate_payload(
        self,
        prompt: str,
        *,
        model: str | None,
        max_tokens: int | None,
    ) -> dict:
        raise NotImplementedError

    @staticmethod
    def _extract_text(data: dict) -> str:
        raise NotImplementedError

    def _record_usage(self, data: dict) -> None:
        usage = data.get("usage") or {}
        self.last_usage = UsageRecord(
            prompt_tokens=int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
            completion_tokens=int(
                usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
            ),
            source=self.provider_name,
        )

    async def _post_json(self, url: str, *, headers: dict[str, str], payload: dict) -> dict:
        try:
            client_kwargs: dict = {"timeout": 90.0}
            if self._transport is not None:
                client_kwargs["transport"] = self._transport
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"{self.provider_name} request failed") from exc
        if not response.is_success:
            raise LLMProviderError(
                f"{self.provider_name} request failed with HTTP {response.status_code}"
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise LLMProviderError(f"{self.provider_name} returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise LLMProviderError(f"{self.provider_name} returned an invalid payload")
        return result


class OpenAIProvider(RemoteLLMProvider):
    provider_name = "openai"

    async def _generate_payload(
        self,
        prompt: str,
        *,
        model: str | None,
        max_tokens: int | None,
    ) -> dict:
        base_url = self.base_url
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        payload = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return await self._post_json(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
        )

    @staticmethod
    def _extract_text(data: dict) -> str:
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content", "") if isinstance(message, dict) else ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ).strip()
        return ""


class AnthropicProvider(RemoteLLMProvider):
    provider_name = "anthropic"

    async def _generate_payload(
        self,
        prompt: str,
        *,
        model: str | None,
        max_tokens: int | None,
    ) -> dict:
        endpoint = self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"
        return await self._post_json(
            f"{endpoint}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            payload={
                "model": model or self.model,
                "max_tokens": max_tokens or 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    @staticmethod
    def _extract_text(data: dict) -> str:
        content = data.get("content") or []
        if not isinstance(content, list):
            return ""
        return "".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()


_CANONICAL_EMBEDDING_TERMS = {
    "人工智能": "ai",
    "大模型": "llm",
    "大型语言模型": "llm",
    "检索增强生成": "rag",
    "后端开发": "backend",
    "服务端开发": "backend",
    "前端开发": "frontend",
    "机器学习": "machine-learning",
    "深度学习": "deep-learning",
    "数据库": "database",
    "实习": "internship",
}


def _embedding_features(text: str) -> list[str]:
    """Create stable mixed-language features for the local fallback vector.

    The previous regex treated a whole uninterrupted Chinese sentence as one
    token. Character n-grams preserve partial phrase overlap and are still
    deterministic, cheap, and dependency-free.
    """

    normalized = re.sub(r"\s+", "", text.casefold())
    features: list[str] = re.findall(r"[a-z0-9][a-z0-9+#._/-]*", normalized)
    for token in re.findall(r"[\u3400-\u9fff]+", normalized):
        if len(token) == 1:
            features.append(token)
            continue
        features.extend(f"zh2:{token[index : index + 2]}" for index in range(len(token) - 1))
        if len(token) >= 3:
            features.extend(f"zh3:{token[index : index + 3]}" for index in range(len(token) - 2))
    for phrase, canonical in _CANONICAL_EMBEDDING_TERMS.items():
        if phrase in normalized:
            features.append(f"canonical:{canonical}")
    return features


def _parse_json_object(value: str) -> dict:
    candidate = value.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(candidate[start : end + 1])
    if not isinstance(parsed, dict):
        raise TypeError("structured output must be a JSON object")
    return parsed


def _response_content_types(data: dict) -> list[str]:
    content = data.get("content")
    if isinstance(content, list):
        return [
            str(item.get("type")) for item in content if isinstance(item, dict) and item.get("type")
        ]
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return ["text"] if content.strip() else []
            if isinstance(content, list):
                return [
                    str(item.get("type"))
                    for item in content
                    if isinstance(item, dict) and item.get("type")
                ]
    return []
