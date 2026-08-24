from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Job


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, *, page: int, page_size: int, search: str | None) -> tuple[list[Job], int]:
        query = select(Job).options(selectinload(Job.skills))
        count_query = select(func.count(Job.id))
        if search:
            pattern = f"%{search}%"
            condition = or_(
                Job.title.ilike(pattern),
                Job.description.ilike(pattern),
                Job.location.ilike(pattern),
            )
            query = query.where(condition)
            count_query = count_query.where(condition)

        total = int((await self.session.scalar(count_query)) or 0)
        jobs = list(
            (
                await self.session.scalars(
                    query.order_by(Job.created_at.desc())
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
                .where(Job.content_hash == content_hash)
            )
        return None

    async def add(self, job: Job) -> Job:
        self.session.add(job)
        await self.session.flush()
        await self.session.refresh(job)
        return job
