from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job, JobSkill
from app.repositories.jobs import JobRepository
from app.schemas.job_intelligence import JobImportRequest
from app.schemas.jobs import JobCreate
from app.services.job_intelligence import JobAnalysis, JobNormalizer
from app.services.mock_jobs import MOCK_JOB_DATASET


class DuplicateJobError(ValueError):
    """Raised when a platform job or content hash already exists."""


class InvalidJobImportError(ValueError):
    """Raised when an imported JD cannot be analyzed."""


@dataclass(frozen=True)
class JobImportResult:
    jobs: list[Job]
    created: int
    duplicates: int


class JobService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = JobRepository(session)
        self.session = session
        self.normalizer = JobNormalizer()

    async def list_jobs(
        self, *, page: int, page_size: int, search: str | None
    ) -> tuple[list[Job], int]:
        return await self.repository.list(page=page, page_size=page_size, search=search)

    async def get_job(self, job_id: UUID) -> Job | None:
        return await self.repository.get(job_id)

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
        try:
            created_job = await self.repository.add(job)
            await self.session.commit()
            return created_job
        except IntegrityError as exc:
            await self.session.rollback()
            raise DuplicateJobError("A job with the same unique key already exists") from exc

    async def import_jobs(self, payload: JobImportRequest) -> JobImportResult:
        if payload.mode == "mock":
            seeds = MOCK_JOB_DATASET[: payload.limit]
            jobs: list[Job] = []
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
        return JobImportResult(
            jobs=[job],
            created=int(was_created),
            duplicates=int(not was_created),
        )

    async def analyze_job(self, job_id: UUID) -> Job | None:
        job = await self.repository.get(job_id)
        if job is None:
            return None
        analysis = self.normalizer.analyze(job.description, title_hint=job.title)
        self._apply_analysis(job, analysis)
        job.skills.clear()
        await self.session.flush()
        self.session.add_all(self._skill_entities(job, analysis))
        await self.session.commit()
        return await self.repository.get(job.id)

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
            normalized_data=self._normalized_data(analysis),
            content_hash=analysis.content_hash,
        )
        self.session.add(job)
        await self.session.flush()
        self.session.add_all(self._skill_entities(job, analysis))
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
            "analysis_version": "JOB_EXTRACTION_V1",
            "structured_job": analysis.structured_job.model_dump(),
            "requirements": analysis.requirements.model_dump(),
            "skills": [skill.name for skill in analysis.skills],
        }

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
