from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.job_pipeline import JobETLPipeline
from app.models.entities import Job
from app.services.job_lifecycle import refresh_lifecycle
from app.services.job_pipeline import build_raw_record, process_and_persist_job
from app.services.knowledge_indexing import enqueue_incremental_knowledge_index


async def backfill(
    *,
    limit: int | None,
    batch_size: int,
    skip_index: bool,
    source: str | None,
    force: bool,
    dry_run: bool,
) -> dict[str, Any]:
    async with SessionLocal() as session:
        statement = select(Job).order_by(Job.created_at, Job.id)
        if limit is not None:
            statement = statement.limit(limit)
        if source:
            statement = statement.where(Job.platform == source)
        job_ids = list((await session.scalars(statement.with_only_columns(Job.id))).all())
        processed: list[str] = []
        warnings = 0
        failures: list[dict[str, str]] = []
        for index, job_id in enumerate(job_ids, start=1):
            try:
                async with session.begin_nested():
                    job = await session.get(Job, job_id)
                    if job is None:
                        raise ValueError("岗位在回填期间已被删除")
                    result = (
                        JobETLPipeline().process(build_raw_record(job))
                        if dry_run
                        else await process_and_persist_job(session, job)
                    )
                    if not dry_run:
                        await session.flush()
                processed.append(str(job_id))
                warnings += len(result.warnings)
            except Exception as exc:
                failures.append({"job_id": str(job_id), "error": str(exc)[:500]})
            if not dry_run and index % batch_size == 0:
                await session.commit()
        if not dry_run:
            await session.commit()
        lifecycle_updated = 0
        if not dry_run:
            lifecycle_updated = await refresh_lifecycle(
                session,
                possibly_expired_days=get_settings().job_possibly_expired_days,
                expired_days=get_settings().job_expired_days,
            )
        run_id = None
        if processed and not skip_index and not dry_run:
            run_id = await enqueue_incremental_knowledge_index(
                session, [UUID(job_id) for job_id in processed], force=force
            )
        return {
            "processed_jobs": len(processed),
            "failed_jobs": len(failures),
            "failures": failures,
            "warnings": warnings,
            "lifecycle_updated": lifecycle_updated,
            "knowledge_index_run_id": str(run_id) if run_id else None,
            "dry_run": dry_run,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill the deterministic Job ETL pipeline")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--source", choices=("boss", "zhaopin", "zhilian"), default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制将回填岗位加入知识库索引，即使内容哈希未变化",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只运行 ETL 和质量检查，不写入岗位、快照或索引任务",
    )
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()
    if args.source == "zhilian":
        args.source = "zhaopin"
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    print(json.dumps(asyncio.run(backfill(**vars(args))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
