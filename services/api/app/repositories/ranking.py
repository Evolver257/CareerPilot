from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Job


class RankingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_candidates(
        self,
        *,
        limit: int,
        job_ids: list[UUID] | None,
        search: str | None,
    ) -> list[Job]:
        query = select(Job).options(selectinload(Job.skills), selectinload(Job.company))
        if job_ids:
            query = query.where(Job.id.in_(job_ids))
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    Job.title.ilike(pattern),
                    Job.description.ilike(pattern),
                    Job.location.ilike(pattern),
                )
            )
        return list(
            (
                await self.session.scalars(
                    query.order_by(Job.created_at.desc(), Job.id).limit(limit)
                )
            ).all()
        )
