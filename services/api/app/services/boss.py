from __future__ import annotations

from urllib.parse import urlsplit

from app.platforms.boss.detectors import ALLOWED_BOSS_HOSTS
from app.platforms.boss.text import decode_boss_salary
from app.schemas.boss import BossVisibleImportRequest
from app.schemas.job_intelligence import JobImportRequest
from app.services.jobs import JobImportResult, JobService


class BossVisibleImportError(ValueError):
    """Raised when a visible-page BOSS import is outside the safe boundary."""


def _approved_url(value: str, *, field: str) -> str:
    hostname = (urlsplit(value).hostname or "").casefold()
    if hostname not in ALLOWED_BOSS_HOSTS:
        raise BossVisibleImportError(f"{field} must be a zhipin.com URL")
    return value


async def import_visible_jobs(
    payload: BossVisibleImportRequest, service: JobService
) -> tuple[list[object], int, int, int]:
    page_url = _approved_url(str(payload.page_url), field="page_url")
    imported: list[object] = []
    created = 0
    duplicates = 0
    updated = 0
    validated_jobs = [
        (item, _approved_url(str(item.job_url), field="job_url")) for item in payload.jobs
    ]
    for item, job_url in validated_jobs:
        salary_text = decode_boss_salary(item.salary_text)
        context = [item.title]
        if item.company_name:
            context.append(f"Company: {item.company_name}")
        if item.location:
            context.append(f"Location: {item.location}")
        if salary_text:
            context.append(f"Salary: {salary_text}")
        context.append(item.description)
        raw_jd = "\n".join(context)
        raw_data: dict[str, object] = {
            "source": "boss_visible_page",
            "collection_mode": "visible_page_only",
            "source_page": page_url,
            "company_name": item.company_name,
            "salary_text": salary_text,
            "salary_encoding_decoded": salary_text != item.salary_text,
            "tags": item.tags,
            "description_source": item.description_source,
            "detail_length": len(item.description),
            "captured_at": payload.captured_at.isoformat() if payload.captured_at else None,
        }
        result: JobImportResult = await service.import_jobs(
            JobImportRequest(
                mode="single",
                raw_jd=raw_jd,
                platform="boss",
                external_job_id=item.external_job_id,
                title=item.title,
                location=item.location,
                source_url=job_url,
                raw_data=raw_data,
            )
        )
        job = result.jobs[0]
        previous_source = (job.raw_data or {}).get("description_source")
        previous_salary = (job.raw_data or {}).get("salary_text")
        if (
            not result.created
            and item.description_source == "detail_panel"
            and (
                previous_source != "detail_panel"
                or item.description not in job.description
                or previous_salary != salary_text
            )
        ):
            job = await service.refresh_imported_job(
                job.id,
                raw_jd=raw_jd,
                raw_data=raw_data,
                title=item.title,
                location=item.location,
                source_url=job_url,
            )
            updated += 1
        imported.append(job)
        created += result.created
        duplicates += result.duplicates
    return imported, created, duplicates, updated
