from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.llm.provider import LLMProvider, LLMProviderError, embed_texts
from app.models.entities import Resume, ResumeChunk
from app.services.resume_chunking import (
    RESUME_CHUNKING_VERSION,
    ResumeChunkDraft,
)


def resume_chunks_need_rebuild(chunks: list[ResumeChunk]) -> bool:
    return not chunks or any(
        (chunk.chunk_metadata or {}).get("chunking_version") != RESUME_CHUNKING_VERSION
        for chunk in chunks
    )


async def replace_resume_chunks(
    session: AsyncSession,
    resume: Resume,
    drafts: list[ResumeChunkDraft],
    provider: LLMProvider,
    settings: Settings,
) -> list[ResumeChunk]:
    """Atomically replace chunks after all embeddings have been generated."""

    vectors = await embed_texts(
        provider,
        [draft.content for draft in drafts],
        model=settings.embedding_model,
    )
    invalid_dimensions = sorted(
        {len(vector) for vector in vectors if len(vector) != settings.embedding_dimensions}
    )
    if invalid_dimensions:
        raise LLMProviderError(
            "resume embedding dimension mismatch: "
            f"expected {settings.embedding_dimensions}, got {invalid_dimensions}"
        )

    signature = str(getattr(provider, "embedding_signature", settings.embedding_model) or "")
    rows = [
        ResumeChunk(
            resume_id=resume.id,
            chunk_type=draft.chunk_type,
            content=draft.content,
            chunk_metadata={
                **draft.metadata,
                "embedding_signature": signature,
                "embedding_dimensions": len(vector),
                "embedding_provider": str(
                    getattr(
                        provider,
                        "embedding_provider_name",
                        getattr(provider, "provider_name", "unknown"),
                    )
                ),
                "embedding_model": str(
                    getattr(provider, "embedding_model", settings.embedding_model)
                ),
            },
            embedding=vector,
        )
        for draft, vector in zip(drafts, vectors, strict=True)
    ]

    await session.execute(delete(ResumeChunk).where(ResumeChunk.resume_id == resume.id))
    session.add_all(rows)
    await session.flush()
    return rows
