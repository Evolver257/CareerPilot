from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Resume, ResumeChunk


class ResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, *, user_id: UUID | None) -> tuple[list[Resume], int]:
        query = (
            select(Resume).options(selectinload(Resume.chunks)).order_by(Resume.created_at.desc())
        )
        count_query = select(func.count(Resume.id))
        if user_id:
            query = query.where(Resume.user_id == user_id)
            count_query = count_query.where(Resume.user_id == user_id)
        total = int((await self.session.scalar(count_query)) or 0)
        resumes = list((await self.session.scalars(query)).unique().all())
        return resumes, total

    async def get(self, resume_id: UUID) -> Resume | None:
        return await self.session.scalar(
            select(Resume).where(Resume.id == resume_id).options(selectinload(Resume.chunks))
        )

    async def get_chunks(self, resume_id: UUID) -> list[ResumeChunk]:
        return list(
            (
                await self.session.scalars(
                    select(ResumeChunk)
                    .where(ResumeChunk.resume_id == resume_id)
                    .order_by(ResumeChunk.created_at, ResumeChunk.id)
                )
            ).all()
        )
