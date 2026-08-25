from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import AgentRun, Application, Campaign, CampaignJob, Job, JobScore


class DashboardRepository:
    """Read-only aggregates used by the product dashboard."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshot(self) -> dict[str, Any]:
        jobs_total = int((await self.session.scalar(select(func.count(Job.id)))) or 0)
        high_match_jobs = int(
            (
                await self.session.scalar(
                    select(func.count(distinct(JobScore.job_id))).where(JobScore.final_score >= 70)
                )
            )
            or 0
        )
        campaigns_total = int((await self.session.scalar(select(func.count(Campaign.id)))) or 0)
        campaign_candidates = int(
            (await self.session.scalar(select(func.count(CampaignJob.id)))) or 0
        )
        applications = list((await self.session.scalars(select(Application.status))).all())
        runs = list(
            (
                await self.session.scalars(
                    select(AgentRun)
                    .options(selectinload(AgentRun.steps))
                    .order_by(AgentRun.created_at.desc())
                )
            ).unique().all()
        )
        return {
            "jobs_total": jobs_total,
            "high_match_jobs": high_match_jobs,
            "campaigns_total": campaigns_total,
            "campaign_candidates": campaign_candidates,
            "application_status": Counter(applications),
            "agent_runs": runs,
        }
