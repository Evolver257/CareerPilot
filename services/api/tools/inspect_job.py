from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.entities import Job, RawJobSnapshot


async def inspect(job_id: UUID) -> dict[str, object]:
    async with SessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise SystemExit(f"job not found: {job_id}")
        snapshots = await session.scalar(
            select(func.count(RawJobSnapshot.id)).where(RawJobSnapshot.job_id == job.id)
        )
        pipeline = (job.normalized_data or {}).get("pipeline") or {}
        return {
            "id": str(job.id),
            "platform": job.platform,
            "title": job.title,
            "source_url": job.source_url,
            "lifecycle_status": job.lifecycle_status,
            "quality": {
                "score": job.data_quality_score,
                "level": job.data_quality_level,
            },
            "raw_snapshot_count": int(snapshots or 0),
            "pipeline": pipeline,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one job's ETL output")
    parser.add_argument("job_id", type=UUID)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(inspect(args.job_id)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
