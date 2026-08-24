from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMProvider(Protocol):
    async def generate(self, prompt: str, *, model: str | None = None) -> str: ...

    async def generate_structured(
        self, prompt: str, schema: type[SchemaT], *, model: str | None = None
    ) -> SchemaT: ...

    async def embed(self, text: str, *, model: str | None = None) -> list[float]: ...


class MockLLMProvider:
    """Deterministic local provider for development and tests without API keys."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    async def generate(self, prompt: str, *, model: str | None = None) -> str:
        return prompt

    async def generate_structured(
        self, prompt: str, schema: type[SchemaT], *, model: str | None = None
    ) -> SchemaT:
        return schema.model_validate({})

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        return self._hash_embedding(text)

    def _hash_embedding(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        tokens: Sequence[str] = re.findall(r"[\w+#.-]+", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            values[index] += sign

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return values
        return [value / norm for value in values]
