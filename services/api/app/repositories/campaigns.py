from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Application, Campaign, CampaignJob, Job


class CampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_campaigns(self) -> tuple[list[Campaign], int]:
        query = (
            select(Campaign)
            .options(
                selectinload(Campaign.campaign_jobs).selectinload(CampaignJob.job),
                selectinload(Campaign.applications).selectinload(Application.job),
            )
            .order_by(Campaign.created_at.desc())
        )
        total = int((await self.session.scalar(select(func.count(Campaign.id)))) or 0)
        campaigns = list((await self.session.scalars(query)).unique().all())
        return campaigns, total

    async def get_campaign(self, campaign_id: UUID) -> Campaign | None:
        return await self.session.scalar(
            select(Campaign)
            .execution_options(populate_existing=True)
            .options(
                selectinload(Campaign.campaign_jobs).selectinload(CampaignJob.job),
                selectinload(Campaign.applications).selectinload(Application.job),
                selectinload(Campaign.resume),
            )
            .where(Campaign.id == campaign_id)
        )

    async def search_jobs(
        self,
        *,
        keywords: list[str],
        cities: list[str],
        limit: int,
    ) -> list[Job]:
        query = select(Job).options(selectinload(Job.skills), selectinload(Job.company))
        normalized_keywords = list(
            dict.fromkeys(value.strip() for value in keywords if value.strip())
        )
        if normalized_keywords:
            keyword_conditions = []
            for keyword in normalized_keywords:
                pattern = f"%{keyword}%"
                keyword_conditions.append(
                    or_(Job.title.ilike(pattern), Job.description.ilike(pattern))
                )
            query = query.where(or_(*keyword_conditions))
        normalized_cities = list(dict.fromkeys(value.strip() for value in cities if value.strip()))
        if normalized_cities:
            query = query.where(
                or_(*(Job.location.ilike(f"%{city}%") for city in normalized_cities))
            )
        return list(
            (
                await self.session.scalars(
                    query.order_by(Job.created_at.desc(), Job.id).limit(limit)
                )
            ).all()
        )

    async def list_applications(self) -> tuple[list[Application], int]:
        query = (
            select(Application)
            .options(selectinload(Application.job), selectinload(Application.campaign))
            .order_by(Application.updated_at.desc())
        )
        total = int((await self.session.scalar(select(func.count(Application.id)))) or 0)
        applications = list((await self.session.scalars(query)).unique().all())
        return applications, total

    async def get_application(self, application_id: UUID) -> Application | None:
        return await self.session.scalar(
            select(Application)
            .options(selectinload(Application.job), selectinload(Application.campaign))
            .where(Application.id == application_id)
        )

    async def commit_campaign(self, campaign: Campaign) -> Campaign:
        self.session.add(campaign)
        await self.session.commit()
        refreshed = await self.get_campaign(campaign.id)
        if refreshed is None:
            raise RuntimeError("Campaign disappeared during persistence")
        return refreshed

    async def commit_application(self, application: Application) -> Application:
        self.session.add(application)
        await self.session.commit()
        refreshed = await self.get_application(application.id)
        if refreshed is None:
            raise RuntimeError("Application disappeared during persistence")
        return refreshed
