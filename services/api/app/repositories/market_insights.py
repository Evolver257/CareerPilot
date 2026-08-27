from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Job, MarketInsightReport


class MarketInsightRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_reports(self) -> tuple[list[MarketInsightReport], int]:
        total = int((await self.session.scalar(select(func.count(MarketInsightReport.id)))) or 0)
        reports = list(
            (
                await self.session.scalars(
                    select(MarketInsightReport).order_by(MarketInsightReport.created_at.desc())
                )
            ).all()
        )
        return reports, total

    async def get_report(self, report_id: UUID) -> MarketInsightReport | None:
        return await self.session.scalar(
            select(MarketInsightReport)
            .execution_options(populate_existing=True)
            .where(MarketInsightReport.id == report_id)
        )

    async def find_cached(self, fingerprint: str) -> MarketInsightReport | None:
        return await self.session.scalar(
            select(MarketInsightReport)
            .where(
                MarketInsightReport.fingerprint == fingerprint,
                MarketInsightReport.status == "SUCCEEDED",
            )
            .order_by(
                case(
                    (
                        MarketInsightReport.llm_source.in_(
                            ["deterministic", "deterministic_fallback"]
                        ),
                        1,
                    ),
                    else_=0,
                ),
                MarketInsightReport.completed_at.desc(),
            )
            .limit(1)
        )

    async def find_active(self, fingerprint: str) -> MarketInsightReport | None:
        return await self.session.scalar(
            select(MarketInsightReport)
            .where(
                MarketInsightReport.fingerprint == fingerprint,
                MarketInsightReport.status.in_(["PENDING", "RUNNING"]),
            )
            .order_by(MarketInsightReport.created_at.asc())
            .limit(1)
        )

    async def candidate_jobs(
        self,
        *,
        cities: list[str],
        job_types: list[str],
        pool_size: int = 500,
    ) -> list[Job]:
        query = select(Job).options(selectinload(Job.skills), selectinload(Job.company))
        if cities:
            query = query.where(or_(*(Job.location.ilike(f"%{city}%") for city in cities)))
        if job_types:
            normalized_types: set[str] = set(job_types)
            if any(item.lower() in {"实习", "intern", "internship"} for item in job_types):
                normalized_types.update({"实习", "Intern", "Internship"})
            if any(item.lower() in {"全职", "full-time", "fulltime"} for item in job_types):
                normalized_types.update({"全职", "Full-time", "Fulltime"})
            query = query.where(Job.job_type.in_(normalized_types))
        return list(
            (
                await self.session.scalars(query.order_by(Job.updated_at.desc()).limit(pool_size))
            ).all()
        )

    async def data_watermark(self) -> tuple[int, str]:
        count, latest = (
            await self.session.execute(select(func.count(Job.id), func.max(Job.updated_at)))
        ).one()
        return int(count or 0), latest.isoformat() if latest else "empty"
