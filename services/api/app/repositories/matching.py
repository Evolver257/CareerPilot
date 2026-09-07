from __future__ import annotations

import math
from uuid import UUID

from sqlalchemy import Float, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Job, JobScore, Resume, ResumeChunk, UserPreference


class MatchingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_job(self, job_id: UUID) -> Job | None:
        return await self.session.scalar(
            select(Job)
            .options(
                selectinload(Job.skills), selectinload(Job.company), selectinload(Job.requirements)
            )
            .where(Job.id == job_id)
        )

    async def get_jobs(self, job_ids: list[UUID]) -> list[Job]:
        if not job_ids:
            return []
        return list(
            (
                await self.session.scalars(
                    select(Job)
                    .options(
                        selectinload(Job.skills),
                        selectinload(Job.company),
                        selectinload(Job.requirements),
                    )
                    .where(Job.id.in_(job_ids))
                )
            ).all()
        )

    async def get_resume(self, resume_id: UUID) -> Resume | None:
        return await self.session.scalar(
            select(Resume).options(selectinload(Resume.chunks)).where(Resume.id == resume_id)
        )

    async def get_default_resume(self) -> Resume | None:
        return await self.session.scalar(
            select(Resume)
            .options(selectinload(Resume.chunks))
            .order_by(Resume.is_default.desc(), Resume.updated_at.desc())
            .limit(1)
        )

    async def get_preferences(self, user_id: UUID) -> UserPreference | None:
        return await self.session.scalar(
            select(UserPreference).where(UserPreference.user_id == user_id)
        )

    async def get_latest_score(
        self,
        *,
        job_id: UUID,
        resume_id: UUID,
        score_version: str,
        input_fingerprint: str | None = None,
        judge_sources: tuple[str, ...] = ("llm",),
    ) -> JobScore | None:
        query = select(JobScore).where(
            JobScore.job_id == job_id,
            JobScore.resume_id == resume_id,
            JobScore.score_version == score_version,
            JobScore.judge_source.in_(judge_sources),
        )
        if input_fingerprint is not None:
            query = query.where(JobScore.input_fingerprint == input_fingerprint)
        return await self.session.scalar(
            query.options(selectinload(JobScore.requirement_matches))
            .order_by(JobScore.created_at.desc())
            .limit(1)
        )

    async def retrieve_resume_chunks(
        self,
        *,
        resume_id: UUID,
        query_embedding: list[float],
        limit: int,
        chunk_types: tuple[str, ...] | None = None,
    ) -> list[tuple[ResumeChunk, float]]:
        bind = self.session.get_bind()
        if bind.dialect.name == "postgresql":
            distance = cast(ResumeChunk.embedding.op("<=>")(query_embedding), Float)
            conditions = [
                ResumeChunk.resume_id == resume_id,
                ResumeChunk.embedding.is_not(None),
            ]
            if chunk_types:
                conditions.append(ResumeChunk.chunk_type.in_(chunk_types))
            rows = (
                await self.session.execute(
                    select(ResumeChunk, distance.label("distance"))
                    .where(*conditions)
                    .order_by(distance)
                    .limit(limit)
                )
            ).all()
            return [
                (chunk, self._clamp_similarity(1.0 - float(raw_distance)))
                for chunk, raw_distance in rows
            ]

        conditions = [ResumeChunk.resume_id == resume_id]
        if chunk_types:
            conditions.append(ResumeChunk.chunk_type.in_(chunk_types))
        chunks = list((await self.session.scalars(select(ResumeChunk).where(*conditions))).all())
        ranked = [
            (chunk, self._cosine_similarity(query_embedding, chunk.embedding or []))
            for chunk in chunks
        ]
        return sorted(ranked, key=lambda item: item[1], reverse=True)[:limit]

    async def add_score(self, score: JobScore) -> JobScore:
        self.session.add(score)
        await self.session.commit()
        await self.session.refresh(score)
        return score

    async def add_scores(self, scores: list[JobScore]) -> list[JobScore]:
        self.session.add_all(scores)
        await self.session.commit()
        for score in scores:
            await self.session.refresh(score)
        return scores

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return MatchingRepository._clamp_similarity(dot / (left_norm * right_norm))

    @staticmethod
    def _clamp_similarity(value: float) -> float:
        return max(0.0, min(1.0, value))
