from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Application,
    CampaignJob,
    Job,
    JobScore,
    JobSkill,
    RawJobSnapshot,
)
from app.platforms.domain import NormalizedJob
from app.platforms.fingerprint import job_fingerprint
from app.repositories.jobs import JobRepository
from app.schemas.job_intelligence import JobImportRequest
from app.schemas.jobs import JobCreate, JobUpdate
from app.services.job_intelligence import JobAnalysis, JobNormalizer
from app.services.job_pipeline import process_and_persist_job
from app.services.knowledge_indexing import enqueue_incremental_knowledge_index
from app.services.mock_jobs import MOCK_JOB_DATASET


class DuplicateJobError(ValueError):
    """Raised when a platform job or content hash already exists."""


class InvalidJobImportError(ValueError):
    """Raised when an imported JD cannot be analyzed."""


class JobNotFoundError(ValueError):
    """Raised when a requested job does not exist."""


class JobInUseError(ValueError):
    """Raised when deleting a job would remove application history."""


@dataclass(frozen=True)
class JobImportResult:
    jobs: list[Job]
    created: int
    duplicates: int


class JobService:
    CURRENT_ANALYSIS_VERSION = "JOB_EXTRACTION_V3"

    def __init__(self, session: AsyncSession) -> None:
        self.repository = JobRepository(session)
        self.session = session
        self.normalizer = JobNormalizer()

    async def enqueue_knowledge_index(self, job_ids: list[UUID]) -> UUID | None:
        """Queue one durable incremental index run for written jobs."""
        return await enqueue_incremental_knowledge_index(self.session, job_ids)

    async def list_jobs(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        company: str | None,
        location: str | None,
        platform: str | None,
        education: str | None,
        experience: str | None,
        salary_floor: int | None,
        salary_ceiling: int | None,
    ) -> tuple[list[Job], int]:
        return await self.repository.list(
            page=page,
            page_size=page_size,
            search=search,
            company=company,
            location=location,
            platform=platform,
            education=education,
            experience=experience,
            salary_floor=salary_floor,
            salary_ceiling=salary_ceiling,
        )

    async def get_job(self, job_id: UUID) -> Job | None:
        return await self.repository.get(job_id)

    async def get_pipeline(self, job_id: UUID) -> dict[str, object] | None:
        job = await self.repository.get(job_id)
        if job is None:
            return None
        snapshots = await self.session.scalar(
            select(func.count(RawJobSnapshot.id)).where(RawJobSnapshot.job_id == job.id)
        )
        pipeline = (job.normalized_data or {}).get("pipeline") or {}
        return {
            "job_id": job.id,
            "status": "ready" if pipeline else "not_processed",
            "quality_score": job.data_quality_score,
            "quality_level": job.data_quality_level,
            "lifecycle_status": job.lifecycle_status,
            "raw_snapshot_count": int(snapshots or 0),
            "canonical": pipeline,
        }

    async def create_job(self, payload: JobCreate) -> Job:
        duplicate = await self.repository.find_duplicate(
            platform=payload.platform,
            external_job_id=payload.external_job_id,
            content_hash=payload.content_hash,
        )
        if duplicate:
            raise DuplicateJobError(
                "A job with the same platform identifier or content hash already exists"
            )

        job = Job(
            **payload.model_dump(exclude={"source_url"}),
            source_url=str(payload.source_url) if payload.source_url else None,
        )
        if not job.job_fingerprint:
            job.job_fingerprint = job_fingerprint(
                company_name=self._company_name(job.raw_data, job.platform_metadata),
                title=job.title,
                city=self._city_from_location(job.location),
            )
        try:
            created_job = await self.repository.add(job)
            await process_and_persist_job(self.session, created_job)
            await self.session.commit()
            await enqueue_incremental_knowledge_index(self.session, [created_job.id])
            return created_job
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateJobError("A job with the same unique key already exists") from exc

    async def update_job(self, job_id: UUID, payload: JobUpdate) -> Job:
        job = await self.repository.get(job_id)
        if job is None:
            raise JobNotFoundError("Job not found")

        values = payload.model_dump(exclude_unset=True, exclude={"source_url"})
        description_changed = "description" in values
        if description_changed:
            analysis = self.normalizer.analyze(
                str(values["description"]),
                title_hint=str(values.get("title") or job.title),
            )
            job.description = str(values["description"])
            job.content_hash = analysis.content_hash
            self._apply_analysis(job, analysis)
            job.skills.clear()
            await self.session.flush()
            self.session.add_all(self._skill_entities(job, analysis))

        for field, value in values.items():
            if field != "description":
                setattr(job, field, value if field != "platform_metadata" else (value or {}))
        if values or "source_url" in payload.model_fields_set:
            job.job_fingerprint = job_fingerprint(
                company_name=self._company_name(job.raw_data, job.platform_metadata),
                title=job.title,
                city=self._city_from_location(job.location),
            )
        if {"salary_min", "salary_max"}.intersection(values):
            job.raw_data = {
                key: value
                for key, value in (job.raw_data or {}).items()
                if key != "salary_text"
            }
        if values or "source_url" in payload.model_fields_set:
            await self.session.execute(delete(JobScore).where(JobScore.job_id == job.id))
        if "source_url" in payload.model_fields_set:
            job.source_url = str(payload.source_url) if payload.source_url else None
        knowledge_changed = bool(
            set(values).intersection(
                {
                    "title",
                    "description",
                    "location",
                    "salary_min",
                    "salary_max",
                    "job_type",
                    "education_requirement",
                    "experience_requirement",
                    "raw_data",
                    "normalized_data",
                    "content_hash",
                }
            )
            or "source_url" in payload.model_fields_set
        )
        if knowledge_changed:
            await process_and_persist_job(self.session, job)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateJobError("Another job already has the same content") from exc
        refreshed = await self.repository.get(job.id)
        if refreshed is None:
            raise JobNotFoundError("Job disappeared during persistence")
        if knowledge_changed:
            await enqueue_incremental_knowledge_index(self.session, [refreshed.id])
        return refreshed

    async def delete_job(self, job_id: UUID) -> None:
        job = await self.repository.get(job_id)
        if job is None:
            raise JobNotFoundError("Job not found")
        referenced = await self.session.scalar(
            select(CampaignJob.id)
            .where(CampaignJob.job_id == job_id)
            .limit(1)
        ) or await self.session.scalar(
            select(Application.id).where(Application.job_id == job_id).limit(1)
        )
        if referenced:
            raise JobInUseError(
                "Job is used by an application plan and cannot be deleted"
            )
        await self.session.delete(job)
        await self.session.commit()

    async def import_jobs(
        self,
        payload: JobImportRequest,
        *,
        auto_index: bool = True,
    ) -> JobImportResult:
        if payload.mode == "mock":
            seeds = MOCK_JOB_DATASET[: payload.limit]
            jobs: list[Job] = []
            created_job_ids: list[UUID] = []
            created = 0
            duplicates = 0
            for seed in seeds:
                job, was_created = await self._import_one(
                    raw_jd=seed.description,
                    platform="mock",
                    external_job_id=seed.external_job_id,
                    title=seed.title,
                    location=seed.location,
                    source_url=None,
                    raw_data={"source": "mock", "role": seed.title},
                )
                jobs.append(job)
                created += int(was_created)
                duplicates += int(not was_created)
                if was_created:
                    created_job_ids.append(job.id)
            if auto_index:
                await enqueue_incremental_knowledge_index(self.session, created_job_ids)
            return JobImportResult(jobs=jobs, created=created, duplicates=duplicates)

        if not payload.raw_jd:
            raise InvalidJobImportError("raw_jd is required for a single JD import")
        job, was_created = await self._import_one(
            raw_jd=payload.raw_jd,
            platform=payload.platform,
            external_job_id=payload.external_job_id,
            title=payload.title,
            location=payload.location,
            source_url=payload.source_url,
            raw_data=payload.raw_data,
        )
        if auto_index and was_created:
            await enqueue_incremental_knowledge_index(self.session, [job.id])
        return JobImportResult(
            jobs=[job],
            created=int(was_created),
            duplicates=int(not was_created),
        )

    async def import_normalized_job(
        self,
        normalized: NormalizedJob,
        *,
        auto_index: bool = True,
    ) -> JobImportResult:
        """Persist a provider-neutral job using the existing import pipeline."""
        platform_metadata = dict(normalized.platform_metadata)
        raw_data = {
            **dict(normalized.raw_data),
            "company_name": normalized.company_name,
            "salary_text": normalized.salary_text,
            "city": normalized.city,
            "district": normalized.district,
            "salary_months": normalized.salary_months,
            "requirements": list(normalized.requirements),
            "skills": list(normalized.skills),
            "benefits": list(normalized.benefits),
            "company_industry": normalized.company_industry,
            "company_size": normalized.company_size,
            "company_stage": normalized.company_stage,
            "description_source": normalized.raw_data.get("description_source", "provider"),
            "raw_description": normalized.description,
            "description_html": normalized.raw_data.get("description_html", normalized.description),
            "education_requirement": normalized.education,
            "experience_requirement": normalized.experience,
            "job_type": normalized.job_type,
            "platform_metadata": platform_metadata,
        }
        context = [normalized.title]
        if normalized.company_name:
            context.append(f"Company: {normalized.company_name}")
        if normalized.location:
            context.append(f"Location: {normalized.location}")
        if normalized.salary_text:
            context.append(f"Salary: {normalized.salary_text}")
        if normalized.experience:
            context.append(f"Experience: {normalized.experience}")
        if normalized.education:
            context.append(f"Education: {normalized.education}")
        context.append(normalized.description or normalized.title)
        result = await self.import_jobs(
            JobImportRequest(
                mode="single",
                raw_jd="\n".join(context),
                platform=normalized.platform,
                external_job_id=normalized.external_job_id,
                title=normalized.title,
                location=normalized.location or normalized.city,
                source_url=normalized.source_url,
                raw_data=raw_data,
            ),
            auto_index=auto_index,
        )
        job = result.jobs[0]
        # Provider parsers already normalized fields such as 8-12K. Preserve
        # those values even when the generic JD analyzer uses a different
        # salary vocabulary or cannot infer the unit from the context line.
        changed = False
        for field, value in (
            ("salary_min", normalized.salary_min),
            ("salary_max", normalized.salary_max),
            ("education_requirement", normalized.education),
            ("experience_requirement", normalized.experience),
            ("job_type", normalized.job_type),
        ):
            if value is not None and getattr(job, field) != value:
                setattr(job, field, value)
                changed = True
        if normalized.location and job.location != normalized.location:
            job.location = normalized.location
            changed = True
        if changed:
            await self.session.execute(delete(JobScore).where(JobScore.job_id == job.id))
            await process_and_persist_job(self.session, job)
            await self.session.commit()
            refreshed = await self.repository.get(job.id)
            if refreshed is not None:
                result = JobImportResult(
                    jobs=[refreshed],
                    created=result.created,
                    duplicates=result.duplicates,
                )
            # Normalized provider fields are applied after the generic import
            # path. Re-index once more so salary/education/skills changes can
            # never leave the durable knowledge document stale.
            if auto_index and refreshed is not None:
                await enqueue_incremental_knowledge_index(self.session, [refreshed.id])
        return result

    async def analyze_job(self, job_id: UUID) -> Job | None:
        job = await self.repository.get(job_id)
        if job is None:
            return None
        analysis = self.normalizer.analyze(job.description, title_hint=job.title)
        normalized = self._normalized_data(analysis)
        if job.normalized_data == normalized and job.skills:
            return job
        self._apply_analysis(job, analysis)
        job.skills.clear()
        await self.session.flush()
        await self.session.execute(delete(JobScore).where(JobScore.job_id == job.id))
        self.session.add_all(self._skill_entities(job, analysis))
        await process_and_persist_job(self.session, job)
        await self.session.commit()
        refreshed = await self.repository.get(job.id)
        if refreshed is not None:
            await enqueue_incremental_knowledge_index(self.session, [refreshed.id])
        return refreshed

    async def refresh_imported_job(
        self,
        job_id: UUID,
        *,
        raw_jd: str,
        raw_data: dict[str, object],
        title: str,
        location: str | None,
        source_url: str,
        auto_index: bool = True,
        normalized_job: NormalizedJob | None = None,
    ) -> Job:
        job = await self.repository.get(job_id)
        if job is None:
            raise InvalidJobImportError("Imported job disappeared before refresh")

        analysis = self.normalizer.analyze(raw_jd, title_hint=title)
        job.description = raw_jd
        job.raw_data = {**(job.raw_data or {}), **raw_data}
        job.title = title or job.title
        job.location = location or job.location
        job.source_url = source_url or job.source_url
        job.platform_metadata = {
            **(job.platform_metadata or {}),
            **(
                raw_data.get("platform_metadata", {})
                if isinstance(raw_data.get("platform_metadata"), dict)
                else {}
            ),
        }
        job.job_fingerprint = job_fingerprint(
            company_name=self._company_name(job.raw_data, job.platform_metadata),
            title=job.title,
            city=self._city_from_location(job.location),
        )
        self._apply_analysis(job, analysis)
        if normalized_job is not None:
            for field, value in (
                ("salary_min", normalized_job.salary_min),
                ("salary_max", normalized_job.salary_max),
                ("education_requirement", normalized_job.education),
                ("experience_requirement", normalized_job.experience),
                ("job_type", normalized_job.job_type),
            ):
                if value is not None:
                    setattr(job, field, value)
        job.skills.clear()
        await self.session.flush()
        await self.session.execute(delete(JobScore).where(JobScore.job_id == job.id))
        self.session.add_all(self._skill_entities(job, analysis))
        await process_and_persist_job(self.session, job, description_html=raw_jd)
        await self.session.commit()
        refreshed = await self.repository.get(job.id)
        if refreshed is None:
            raise InvalidJobImportError("Refreshed job disappeared during persistence")
        if auto_index:
            await enqueue_incremental_knowledge_index(self.session, [refreshed.id])
        return refreshed

    async def mark_collected(
        self,
        job_id: UUID,
        *,
        collected_at: datetime,
        source_page: str | None = None,
    ) -> Job:
        """Refresh collection freshness without replacing a richer stored JD."""
        job = await self.repository.get(job_id)
        if job is None:
            raise InvalidJobImportError("Imported job disappeared before collection refresh")
        content_updated_at = job.updated_at
        refreshed_raw_data = {
            **(job.raw_data or {}),
            "captured_at": collected_at.isoformat(),
            **({"source_page": source_page} if source_page else {}),
        }
        # Re-discovery changes collection freshness, not the JD itself. Keep the
        # content timestamp stable so matching/LLM caches remain reusable.
        await self.session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(
                last_collected_at=collected_at,
                raw_data=refreshed_raw_data,
                updated_at=content_updated_at,
            )
        )
        await self.session.commit()
        refreshed = await self.repository.get(job.id)
        if refreshed is None:
            raise InvalidJobImportError("Collected job disappeared during persistence")
        return refreshed

    async def _import_one(
        self,
        *,
        raw_jd: str,
        platform: str,
        external_job_id: str | None,
        title: str | None,
        location: str | None,
        source_url: str | None,
        raw_data: dict[str, object],
    ) -> tuple[Job, bool]:
        analysis = self.normalizer.analyze(raw_jd, title_hint=title)
        duplicate = await self.repository.find_duplicate(
            platform=platform,
            external_job_id=external_job_id,
            content_hash=analysis.content_hash,
        )
        if duplicate:
            return duplicate, False

        profile = analysis.structured_job
        job = Job(
            platform=platform,
            external_job_id=external_job_id,
            title=profile.title or "Untitled Job",
            description=raw_jd,
            location=location or profile.location or None,
            salary_min=profile.salary.minimum,
            salary_max=profile.salary.maximum,
            job_type=profile.job_type or None,
            education_requirement=profile.education_requirement or None,
            experience_requirement=profile.experience_requirement or None,
            source_url=source_url,
            raw_data=raw_data,
            platform_metadata=(
                raw_data.get("platform_metadata", {})
                if isinstance(raw_data.get("platform_metadata"), dict)
                else {}
            ),
            normalized_data=self._normalized_data(analysis),
            content_hash=analysis.content_hash,
        )
        job.job_fingerprint = job_fingerprint(
            company_name=self._company_name(job.raw_data, job.platform_metadata),
            title=job.title,
            city=self._city_from_location(job.location),
        )
        self.session.add(job)
        await self.session.flush()
        self.session.add_all(self._skill_entities(job, analysis))
        await process_and_persist_job(self.session, job)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateJobError("A job with the same unique key already exists") from exc
        refreshed = await self.repository.get(job.id)
        if refreshed is None:
            raise InvalidJobImportError("Imported job disappeared during persistence")
        return refreshed, True

    @staticmethod
    def _normalized_data(analysis: JobAnalysis) -> dict[str, object]:
        return {
            "analysis_version": JobService.CURRENT_ANALYSIS_VERSION,
            "structured_job": analysis.structured_job.model_dump(),
            "requirements": analysis.requirements.model_dump(),
            "skills": [skill.name for skill in analysis.skills],
        }

    @staticmethod
    def _company_name(
        raw_data: dict[str, object] | None,
        platform_metadata: dict[str, object] | None,
    ) -> str | None:
        for values in (platform_metadata or {}, raw_data or {}):
            value = values.get("company_name")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _city_from_location(location: str | None) -> str | None:
        return location.split("·", 1)[0].strip() if location and location.strip() else None

    def _apply_analysis(self, job: Job, analysis: JobAnalysis) -> None:
        profile = analysis.structured_job
        job.normalized_data = self._normalized_data(analysis)
        job.title = job.title or profile.title or "Untitled Job"
        job.location = job.location or profile.location or None
        job.salary_min = profile.salary.minimum
        job.salary_max = profile.salary.maximum
        job.job_type = profile.job_type or None
        job.education_requirement = profile.education_requirement or None
        job.experience_requirement = profile.experience_requirement or None
        job.content_hash = job.content_hash or analysis.content_hash

    @staticmethod
    def _skill_entities(job: Job, analysis: JobAnalysis) -> list[JobSkill]:
        return [
            JobSkill(
                job_id=job.id,
                skill_name=skill.name,
                skill_type=skill.skill_type,
                importance=skill.importance,
                confidence=skill.confidence,
            )
            for skill in analysis.skills
        ]
