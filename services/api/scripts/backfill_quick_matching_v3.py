from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Job, Resume
from app.services.quick_matching import QuickMatchingService


async def backfill(
    *, batch_size: int, limit: int | None, resume_id: UUID | None
) -> dict[str, Any]:
    async with SessionLocal() as session:
        resume = (
            await session.get(Resume, resume_id)
            if resume_id
            else await session.scalar(
                select(Resume).order_by(Resume.is_default.desc(), Resume.updated_at.desc()).limit(1)
            )
        )
        if resume is None:
            raise RuntimeError("No resume is available for Quick Matching V3 backfill")
        statement = select(Job.id).order_by(Job.created_at, Job.id)
        if limit is not None:
            statement = statement.limit(limit)
        job_ids = list((await session.scalars(statement)).all())
        processed = cached = 0
        failures: list[dict[str, str]] = []
        service = QuickMatchingService(session)

        for offset in range(0, len(job_ids), batch_size):
            batch = job_ids[offset : offset + batch_size]
            try:
                result = await service.score_many(job_ids=batch, resume_id=resume.id)
                processed += len(result.items)
                cached += sum(item.cached for item in result.items)
            except Exception:
                await session.rollback()
                for job_id in batch:
                    try:
                        result = await service.score_many(job_ids=[job_id], resume_id=resume.id)
                        processed += 1
                        cached += int(result.items[0].cached)
                    except Exception as exc:
                        await session.rollback()
                        failures.append({"job_id": str(job_id), "error": str(exc)[:500]})
            print(
                json.dumps(
                    {
                        "processed": processed,
                        "total": len(job_ids),
                        "failed": len(failures),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        return {
            "score_version": QuickMatchingService.SCORE_VERSION,
            "resume_id": str(resume.id),
            "total_jobs": len(job_ids),
            "processed_jobs": processed,
            "cached_jobs": cached,
            "failed_jobs": len(failures),
            "failures": failures,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently backfill deterministic Quick Matching V3 scores"
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume-id", type=UUID, default=None)
    args = parser.parse_args()
    if args.batch_size < 1 or args.batch_size > 200:
        parser.error("--batch-size must be between 1 and 200")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    print(json.dumps(asyncio.run(backfill(**vars(args))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
