"""Backfill exact semantic token counts without recomputing embeddings.

Usage:
    python -m scripts.backfill_semantic_token_counts
    python -m scripts.backfill_semantic_token_counts --batch-size 1000 --force
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal, engine
from app.llm.tokenization import TokenCounter, token_counter_for_provider
from app.models.entities import JobKnowledgeChunk, ResumeChunk
from app.services.llm_settings import LLMSettingsService


@dataclass
class BackfillStats:
    scanned: int = 0
    updated: int = 0


def _metadata_is_current(metadata: dict, counter: TokenCounter, token_count: int) -> bool:
    return (
        metadata.get("tokenizer_signature") == counter.signature
        and metadata.get("token_count_exact") is True
        and metadata.get("token_count") == token_count
    )


async def _backfill_job_chunks(
    counter: TokenCounter,
    *,
    batch_size: int,
    force: bool,
) -> BackfillStats:
    stats = BackfillStats()
    last_id: UUID | None = None
    while True:
        async with SessionLocal() as session:
            statement = select(JobKnowledgeChunk).order_by(JobKnowledgeChunk.id).limit(batch_size)
            if last_id is not None:
                statement = statement.where(JobKnowledgeChunk.id > last_id)
            rows = list((await session.scalars(statement)).all())
            if not rows:
                break
            for row in rows:
                count = counter.count(row.content)
                metadata = dict(row.chunk_metadata or {})
                current = _metadata_is_current(metadata, counter, count)
                if force or not current or row.token_count != count:
                    row.token_count = count
                    row.chunk_metadata = {
                        **metadata,
                        "token_count": count,
                        "tokenizer_signature": counter.signature,
                        "token_count_exact": True,
                    }
                    stats.updated += 1
                stats.scanned += 1
            last_id = rows[-1].id
            await session.commit()
            print(f"job chunks: scanned={stats.scanned} updated={stats.updated}", flush=True)
    return stats


async def _backfill_resume_chunks(
    counter: TokenCounter,
    *,
    batch_size: int,
    force: bool,
) -> BackfillStats:
    stats = BackfillStats()
    last_id: UUID | None = None
    while True:
        async with SessionLocal() as session:
            statement = select(ResumeChunk).order_by(ResumeChunk.id).limit(batch_size)
            if last_id is not None:
                statement = statement.where(ResumeChunk.id > last_id)
            rows = list((await session.scalars(statement)).all())
            if not rows:
                break
            for row in rows:
                count = counter.count(row.content)
                metadata = dict(row.chunk_metadata or {})
                if force or not _metadata_is_current(metadata, counter, count):
                    row.chunk_metadata = {
                        **metadata,
                        "token_count": count,
                        "tokenizer_signature": counter.signature,
                        "token_count_exact": True,
                    }
                    stats.updated += 1
                stats.scanned += 1
            last_id = rows[-1].id
            await session.commit()
            print(f"resume chunks: scanned={stats.scanned} updated={stats.updated}", flush=True)
    return stats


async def run(*, batch_size: int, force: bool) -> None:
    async with SessionLocal() as session:
        provider = await LLMSettingsService(session).get_runtime_embedding_provider()
    counter = token_counter_for_provider(provider)
    if not counter.exact:
        raise RuntimeError(
            "当前 Embedding Provider 不暴露 tokenizer；拒绝把近似值回填为精确 Token 数"
        )
    print(f"tokenizer={counter.signature}", flush=True)
    jobs = await _backfill_job_chunks(counter, batch_size=batch_size, force=force)
    resumes = await _backfill_resume_chunks(counter, batch_size=batch_size, force=force)
    print(
        "completed "
        f"job_scanned={jobs.scanned} job_updated={jobs.updated} "
        f"resume_scanned={resumes.scanned} resume_updated={resumes.updated}",
        flush=True,
    )


async def _main(*, batch_size: int, force: bool) -> None:
    try:
        await run(batch_size=batch_size, force=force)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 5000:
        parser.error("--batch-size must be between 1 and 5000")
    asyncio.run(_main(batch_size=args.batch_size, force=args.force))


if __name__ == "__main__":
    main()
