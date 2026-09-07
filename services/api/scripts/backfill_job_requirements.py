from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.entities import Job
from app.services.requirement_matching import sync_job_requirements


async def backfill(*, batch_size: int, limit: int | None) -> dict[str, int]:
    async with SessionLocal() as session:
        query = select(Job.id).order_by(Job.created_at, Job.id)
        if limit is not None:
            query = query.limit(limit)
        job_ids = list((await session.scalars(query)).all())
        processed = failed = requirements = 0
        for index, job_id in enumerate(job_ids, start=1):
            try:
                async with session.begin_nested():
                    job = await session.get(Job, job_id)
                    if job is None:
                        continue
                    rows = await sync_job_requirements(session, job)
                    requirements += len(rows)
                    processed += 1
            except Exception:
                failed += 1
            if index % batch_size == 0:
                await session.commit()
        await session.commit()
        return {"processed_jobs": processed, "failed_jobs": failed, "requirements": requirements}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill atomic JD requirements")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(backfill(**vars(args))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
