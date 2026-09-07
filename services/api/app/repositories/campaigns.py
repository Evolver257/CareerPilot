from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, func, or_, select
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
                selectinload(Campaign.ranking_runs),
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
                selectinload(Campaign.ranking_runs),
            )
            .where(Campaign.id == campaign_id)
        )

    async def search_jobs(
        self,
        *,
        keywords: list[str],
        cities: list[str],
        limit: int,
        offset: int = 0,
        collected_after: datetime | None = None,
        platform: str | None = None,
        salary_min: int | None = None,
        salary_max: int | None = None,
        education: list[str] | None = None,
        experience: list[str] | None = None,
        job_types: list[str] | None = None,
        industries: list[str] | None = None,
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
        if collected_after is not None:
            query = query.where(Job.last_collected_at >= collected_after)
        if platform:
            query = query.where(Job.platform == platform)
        if salary_min is not None:
            query = query.where(Job.salary_max.is_(None) | (Job.salary_max >= salary_min))
        if salary_max is not None:
            query = query.where(Job.salary_min.is_(None) | (Job.salary_min <= salary_max))
        normalized_education = [value.strip() for value in (education or []) if value.strip()]
        if normalized_education:
            query = query.where(
                or_(
                    *(
                        Job.education_requirement.ilike(f"%{value}%")
                        for value in normalized_education
                    )
                )
            )
        normalized_experience = [value.strip() for value in (experience or []) if value.strip()]
        if normalized_experience:
            query = query.where(
                or_(
                    *(
                        Job.experience_requirement.ilike(f"%{value}%")
                        for value in normalized_experience
                    )
                )
            )
        normalized_job_types = [value.strip() for value in (job_types or []) if value.strip()]
        if normalized_job_types:
            query = query.where(
                or_(*(Job.job_type.ilike(f"%{value}%") for value in normalized_job_types))
            )
        normalized_industries = [value.strip() for value in (industries or []) if value.strip()]
        if normalized_industries:
            query = query.where(
                or_(
                    *(
                        Job.raw_data.cast(Text).ilike(f"%{value}%")
                        for value in normalized_industries
                    )
                )
            )
        return list(
            (
                await self.session.scalars(
                    query.order_by(Job.last_collected_at.desc(), Job.id).offset(offset).limit(limit)
                )
            ).all()
        )

    async def get_jobs_by_ids(self, job_ids: list[UUID]) -> list[Job]:
        if not job_ids:
            return []
        return list(
            (
                await self.session.scalars(
                    select(Job)
                    .options(selectinload(Job.skills), selectinload(Job.company))
                    .where(Job.id.in_(job_ids))
                )
            ).all()
        )

    async def list_applications(
        self, *, page: int = 1, page_size: int = 50,
        statuses: list[str] | None = None, campaign_id: UUID | None = None,
        platform: str | None = None,
    ) -> tuple[list[Application], int, dict[str, int]]:
        conditions = []
        if campaign_id is not None:
            conditions.append(Application.campaign_id == campaign_id)
        if platform:
            conditions.append(Application.platform == platform)
        counts = dict((await self.session.execute(
            select(Application.status, func.count(Application.id))
            .where(*conditions).group_by(Application.status)
        )).all())
        if statuses:
            conditions.append(Application.status.in_(statuses))
        query = (
            select(Application)
            .options(selectinload(Application.job), selectinload(Application.campaign))
            .where(*conditions)
            .order_by(Application.updated_at.desc(), Application.id)
            .offset((page - 1) * page_size).limit(page_size)
        )
        total = int((await self.session.scalar(
            select(func.count(Application.id)).where(*conditions)
        )) or 0)
        applications = list((await self.session.scalars(query)).unique().all())
        return applications, total, counts

    async def get_application(self, application_id: UUID) -> Application | None:
        return await self.session.scalar(
            select(Application)
            .options(selectinload(Application.job), selectinload(Application.campaign))
            .where(Application.id == application_id)
        )

    async def commit_campaign(self, campaign: Campaign) -> Campaign:
        from app.services.campaign_completion import reconcile_campaign_completion

        self.session.add(campaign)
        await self.session.flush()
        await reconcile_campaign_completion(self.session, campaign.id)
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
