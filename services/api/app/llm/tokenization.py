from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class TokenCounter(Protocol):
    """Small provider-neutral boundary used by semantic chunkers."""

    signature: str
    exact: bool

    def count(self, text: str) -> int: ...


def approximate_multilingual_tokens(text: str) -> int:
    """Conservative fallback when an embedding tokenizer is unavailable."""

    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    ascii_words = re.findall(r"[A-Za-z0-9_+#.\-/]+", text)
    ascii_tokens = sum(max(1, math.ceil(len(word) / 4)) for word in ascii_words)
    punctuation = len(re.findall(r"[^\w\s\u3400-\u9fff]", text))
    return cjk + ascii_tokens + punctuation


@dataclass(frozen=True)
class CallableTokenCounter:
    callback: Callable[[str], int]
    signature: str
    exact: bool

    def count(self, text: str) -> int:
        value = int(self.callback(text))
        if value < 0:
            raise ValueError("token counter returned a negative value")
        return value


APPROXIMATE_TOKEN_COUNTER = CallableTokenCounter(
    callback=approximate_multilingual_tokens,
    signature="approximate:multilingual-cjk-ascii-v2",
    exact=False,
)


def token_counter_for_provider(provider: object | None) -> TokenCounter:
    """Use the embedding model tokenizer when the provider exposes one.

    Remote embedding APIs do not necessarily expose their tokenizer. Those
    providers intentionally receive a labelled approximate counter instead of
    pretending the estimate is exact.
    """

    callback = getattr(provider, "count_embedding_tokens", None)
    if not callable(callback):
        return APPROXIMATE_TOKEN_COUNTER
    signature = str(
        getattr(provider, "tokenizer_signature", "provider:embedding-tokenizer")
        or "provider:embedding-tokenizer"
    )
    return CallableTokenCounter(callback=callback, signature=signature, exact=True)


def max_prefix_end(
    text: str,
    *,
    max_chars: int,
    max_tokens: int,
    counter: TokenCounter,
) -> int:
    """Return a source-preserving prefix boundary within both budgets."""

    high = min(len(text), max(1, max_chars))
    if counter.count(text[:high]) <= max_tokens:
        return high

    low = 1
    while low < high:
        middle = (low + high + 1) // 2
        if counter.count(text[:middle]) <= max_tokens:
            low = middle
        else:
            high = middle - 1
    end = max(1, low)
    # Token merges can make counts locally non-monotonic. Validate the final
    # boundary rather than trusting binary search alone.
    while end > 1 and counter.count(text[:end]) > max_tokens:
        end -= 1
    return end
