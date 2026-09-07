from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Job


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
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
        query = select(Job).options(selectinload(Job.skills))
        count_query = select(func.count(Job.id))
        conditions = []
        if search:
            pattern = f"%{search}%"
            conditions.append(or_(
                Job.title.ilike(pattern),
                Job.description.ilike(pattern),
                Job.location.ilike(pattern),
                cast(Job.raw_data, String).ilike(pattern),
            ))
        if company:
            company_pattern = f"%{company}%"
            conditions.append(or_(
                Job.raw_data["company_name"].as_string().ilike(company_pattern),
                cast(Job.raw_data, String).ilike(company_pattern),
            ))
        if location:
            conditions.append(Job.location.ilike(f"%{location}%"))
        if platform:
            conditions.append(Job.platform == platform)
        if education:
            conditions.append(Job.education_requirement.ilike(f"%{education}%"))
        if experience:
            conditions.append(Job.experience_requirement.ilike(f"%{experience}%"))
        if salary_floor is not None:
            conditions.append(func.coalesce(Job.salary_max, Job.salary_min) >= salary_floor)
        if salary_ceiling is not None:
            conditions.append(func.coalesce(Job.salary_min, Job.salary_max) <= salary_ceiling)
        if conditions:
            query = query.where(*conditions)
            count_query = count_query.where(*conditions)

        total = int((await self.session.scalar(count_query)) or 0)
        jobs = list(
            (
                await self.session.scalars(
                    query.order_by(Job.last_collected_at.desc(), Job.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return jobs, total

    async def get(self, job_id: UUID) -> Job | None:
        return await self.session.scalar(
            select(Job).options(selectinload(Job.skills)).where(Job.id == job_id)
        )

    async def find_duplicate(
        self, *, platform: str, external_job_id: str | None, content_hash: str | None
    ) -> Job | None:
        if external_job_id:
            duplicate = await self.session.scalar(
                select(Job)
                .options(selectinload(Job.skills))
                .where(Job.platform == platform, Job.external_job_id == external_job_id)
            )
            if duplicate:
                return duplicate
        if content_hash:
            return await self.session.scalar(
                select(Job)
                .options(selectinload(Job.skills))
                .where(Job.platform == platform, Job.content_hash == content_hash)
            )
        return None

    async def add(self, job: Job) -> Job:
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job
