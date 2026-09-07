from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.job_pipeline import JobETLPipeline, RawJobRecord
from app.job_pipeline.dedup import is_probable_duplicate
from app.models.entities import Job, RawJobSnapshot
from app.services.requirement_matching import sync_job_requirements


def _raw_hash(record: RawJobRecord) -> str:
    payload = json.dumps(record.raw_payload, ensure_ascii=False, sort_keys=True, default=str)
    value = "\n".join(
        (
            record.raw_title,
            record.raw_salary or "",
            record.raw_location or "",
            record.description_html,
            payload,
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _company(job: Job) -> str:
    for payload in (job.platform_metadata or {}, job.raw_data or {}):
        for key in ("company_name", "company", "companyName"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    loaded_company = job.__dict__.get("company")
    return loaded_company.name if loaded_company is not None else ""


def build_raw_record(
    job: Job, *, description_html: str | None = None, collected_at: datetime | None = None
) -> RawJobRecord:
    raw = dict(job.raw_data or {})
    return RawJobRecord(
        source=job.platform,
        source_job_id=job.external_job_id,
        source_url=job.source_url,
        raw_title=job.title,
        raw_salary=str(raw.get("salary_text") or raw.get("salary") or "") or None,
        raw_location=job.location,
        description_html=description_html
        or str(raw.get("description_html") or raw.get("raw_description") or job.description),
        raw_payload=raw,
        collected_at=collected_at or job.last_collected_at or datetime.now(UTC),
        company_name=_company(job) or None,
        education=job.education_requirement,
        experience=job.experience_requirement,
        employment_type=job.job_type,
    )


async def process_and_persist_job(
    session: AsyncSession,
    job: Job,
    *,
    description_html: str | None = None,
    collected_at: datetime | None = None,
) -> Any:
    """Run ETL and persist derived metadata plus a replayable raw snapshot."""

    record = build_raw_record(job, description_html=description_html, collected_at=collected_at)
    result = JobETLPipeline().process(record)
    normalized = dict(job.normalized_data or {})
    normalized["pipeline"] = result.canonical
    job.normalized_data = normalized
    job.lifecycle_status = result.canonical["lifecycle_status"]
    job.data_quality_score = result.quality_score
    job.data_quality_level = result.quality_level

    snapshot_hash = _raw_hash(record)
    existing_snapshot = await session.scalar(
        select(RawJobSnapshot).where(
            RawJobSnapshot.job_id == job.id,
            RawJobSnapshot.content_hash == snapshot_hash,
        )
    )
    if existing_snapshot is None:
        session.add(
            RawJobSnapshot(
                job_id=job.id,
                source_platform=record.source,
                external_job_id=record.source_job_id,
                source_url=record.source_url,
                raw_title=record.raw_title,
                raw_salary=record.raw_salary,
                raw_location=record.raw_location,
                description_html=record.description_html,
                raw_payload=record.raw_payload,
                content_hash=snapshot_hash,
                collected_at=record.collected_at or datetime.now(UTC),
            )
        )
    await _assign_duplicate_group(session, job, result.canonical)
    await sync_job_requirements(session, job)
    return result


async def _assign_duplicate_group(
    session: AsyncSession, job: Job, canonical: dict[str, Any]
) -> None:
    location_data = canonical.get("location") or {}
    company = str(canonical.get("company") or "").strip()
    title = str(canonical.get("title") or job.title).strip()
    location = str(location_data.get("normalized") or job.location or "").strip()
    if not company or not title:
        return
    candidates = list(
        (
            await session.scalars(
                select(Job)
                .where(Job.id != job.id, Job.title.ilike(f"%{title[:120]}%"))
                .order_by(Job.created_at)
                .limit(50)
            )
        ).all()
    )
    current = {
        "source": job.platform,
        "source_job_id": job.external_job_id,
        "company": company,
        "title": title,
        "location": location,
    }
    group = None
    for candidate in candidates:
        other_raw = candidate.raw_data or {}
        other = {
            "source": candidate.platform,
            "source_job_id": candidate.external_job_id,
            "company": str(other_raw.get("company_name") or other_raw.get("company") or "").strip(),
            "title": candidate.title,
            "location": candidate.location or "",
        }
        if is_probable_duplicate(current, other):
            group = candidate.duplicate_group_id
            break
    if group is None:
        group = hashlib.sha256(
            "|".join((company.casefold(), title.casefold(), location.casefold())).encode()
        ).hexdigest()[:32]
    job.duplicate_group_id = group
