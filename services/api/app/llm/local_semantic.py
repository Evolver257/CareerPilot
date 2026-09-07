"""Optional CPU semantic models. No remote inference or silent hash fallback."""

from __future__ import annotations

import asyncio
import math
import threading
from functools import lru_cache

from app.llm.provider import LLMProviderError

EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"
RERANK_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODEL_REVISIONS = {
    # Pin the model revision so a later upstream update cannot silently
    # invalidate persisted vectors without changing the embedding signature.
    EMBED_MODEL: "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
    RERANK_MODEL: "1427fd652930e4ba29e8149678df786c240d8825",
}
TOKENIZER_FAMILY = "Qwen2Tokenizer"
_lock = threading.Lock()


@lru_cache(maxsize=2)
def embedding_model(name: str, cache: str | None):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        name,
        device="cpu",
        cache_folder=cache,
        trust_remote_code=False,
        revision=MODEL_REVISIONS.get(name),
    )


@lru_cache(maxsize=2)
def embedding_tokenizer(name: str, cache: str | None):
    from transformers import AutoTokenizer

    # SentenceTransformer resolves this model to Qwen2Tokenizer. Loading the
    # tokenizer independently avoids loading 0.6B model weights for count-only
    # maintenance commands while keeping the same pinned model revision.
    return AutoTokenizer.from_pretrained(
        name,
        cache_dir=cache,
        revision=MODEL_REVISIONS.get(name),
        trust_remote_code=False,
        use_fast=False,
    )


@lru_cache(maxsize=2)
def reranking_model(name: str, cache: str | None):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(
        name,
        device="cpu",
        cache_folder=cache,
        trust_remote_code=False,
        revision=MODEL_REVISIONS.get(name),
    )


class LocalSemanticProvider:
    provider_name = "sentence_transformers"
    embedding_provider_name = "sentence_transformers"

    def __init__(
        self,
        model: str = EMBED_MODEL,
        cache: str | None = None,
        dimensions: int = 1024,
    ):
        self.embedding_model = model
        self.model = model
        self.cache = cache
        self.dimensions = dimensions
        revision = MODEL_REVISIONS.get(model, "unversioned")
        self.embedding_signature = (
            f"st:{model}@{revision}:{dimensions}:normalized:query-prompt:v2"
        )
        self.tokenizer_signature = f"hf:{model}@{revision}:{TOKENIZER_FAMILY}"

    def count_embedding_tokens(self, text: str) -> int:
        """Count with the exact tokenizer used by SentenceTransformer."""

        if not text:
            return 0
        try:
            with _lock:
                tokenizer = embedding_tokenizer(self.model, self.cache)
                return len(tokenizer.encode(text, add_special_tokens=False))
        except Exception as exc:
            raise LLMProviderError(
                f"本地 Embedding Tokenizer 不可用（{type(exc).__name__}）"
            ) from exc

    def encode(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        try:
            with _lock:
                encode_kwargs = {
                    "batch_size": 16,
                    "normalize_embeddings": True,
                    "show_progress_bar": False,
                }
                # Qwen3's model card recommends the query prompt for search
                # queries and no prompt for indexed documents.  Keeping this
                # distinction here makes the same provider usable for both
                # indexing and retrieval without changing the LLM interface.
                if is_query and self.model == EMBED_MODEL:
                    encode_kwargs["prompt_name"] = "query"
                vectors = (
                    embedding_model(self.model, self.cache)
                    .encode(texts, **encode_kwargs)
                    .tolist()
                )
            if any(
                len(v) != self.dimensions or not all(math.isfinite(x) for x in v) for v in vectors
            ):
                raise ValueError(
                    f"知识库要求 {self.dimensions} 维有限向量；"
                    "请检查模型配置并重建索引"
                )
            return vectors
        except Exception as exc:
            raise LLMProviderError(
                f"本地语义模型不可用（{type(exc).__name__}），未降级为 Hash 向量"
            ) from exc

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        del model
        return (await asyncio.to_thread(self.encode, [text], is_query=True))[0]

    async def embed_many(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        del model
        if not texts:
            return []
        return await asyncio.to_thread(self.encode, texts, is_query=False)


class SemanticReranker:
    def __init__(self, model: str = RERANK_MODEL, cache: str | None = None):
        self.model, self.cache = model, cache

    def predict(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        with _lock:
            values = (
                reranking_model(self.model, self.cache)
                .predict(
                    [(query, document) for document in documents],
                    batch_size=16,
                    show_progress_bar=False,
                )
                .tolist()
            )
        if len(values) != len(documents) or not all(math.isfinite(v) for v in values):
            raise ValueError("Invalid reranker scores")
        return values

    async def rerank(self, query, candidates, limit):
        scores = await asyncio.to_thread(
            self.predict,
            query,
            [f"{item.citation.title}\n{item.citation.evidence}" for item in candidates],
        )
        for item, score in zip(candidates, scores, strict=True):
            item.rerank_score = 1 / (1 + math.exp(-max(-40, min(40, score))))
        return sorted(candidates, key=lambda item: item.rerank_score, reverse=True)[:limit]
