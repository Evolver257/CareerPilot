from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.states import BrowserActionType
from app.platforms.base import (
    CaptchaRequiredError,
    DomChangedError,
    JobPlatformAdapter,
    LoginRequiredError,
    PlatformJob,
    PlatformLimitError,
    PreparedApplication,
    SubmittedApplication,
)
from app.repositories.campaigns import CampaignRepository
from app.schemas.browser import BrowserAction, BrowserTarget


class MockPlatformAdapter(JobPlatformAdapter):
    """Deterministic recruitment site adapter used by tests and local demos."""

    name = "mock"

    def __init__(self, session: AsyncSession) -> None:
        self.repository = CampaignRepository(session)

    async def search_jobs(
        self, *, keywords: list[str], cities: list[str], limit: int
    ) -> list[PlatformJob]:
        jobs = await self.repository.search_jobs(keywords=keywords, cities=cities, limit=limit)
        return [self._job(job) for job in jobs]

    async def get_job_detail(self, job_id: UUID) -> PlatformJob | None:
        jobs = await self.repository.search_jobs(keywords=[], cities=[], limit=300)
        return next((self._job(job) for job in jobs if job.id == job_id), None)

    async def normalize_job(self, job: PlatformJob) -> dict[str, object]:
        return {
            "id": str(job.id),
            "title": job.title,
            "location": job.location,
            "platform": job.platform,
        }

    async def prepare_application(
        self, *, application_id: UUID, scenario: str
    ) -> PreparedApplication:
        application = await self.repository.get_application(application_id)
        if application is None:
            raise ValueError("Application not found")
        job = application.job
        actions = [
            BrowserAction(
                action=BrowserActionType.NAVIGATE,
                url=f"http://localhost:3000/mock-platform/jobs/{job.id}?task={application_id}",
            ),
            BrowserAction(action=BrowserActionType.CHECK_STATE),
            BrowserAction(
                action=BrowserActionType.CLICK,
                target=BrowserTarget(strategy="semantic", name="立即投递"),
            ),
            BrowserAction(action=BrowserActionType.EXTRACT, metadata={"fields": ["result"]}),
        ]
        return PreparedApplication(
            actions=actions,
            context={
                "application_id": str(application.id),
                "job_id": str(job.id),
                "scenario": scenario.upper(),
            },
        )

    async def submit_application(
        self, *, application_id: UUID, scenario: str, observations: dict[str, object]
    ) -> SubmittedApplication:
        scenario_name = scenario.upper()
        if scenario_name == "CAPTCHA_REQUIRED":
            raise CaptchaRequiredError("Mock platform CAPTCHA requires user action")
        if scenario_name == "LOGIN_REQUIRED":
            raise LoginRequiredError("Mock platform login is required")
        if scenario_name == "PLATFORM_LIMIT":
            raise PlatformLimitError("Mock platform application limit reached")
        if scenario_name == "DOM_CHANGED":
            raise DomChangedError("Mock platform DOM no longer matches the adapter")
        if scenario_name == "FAILED":
            raise RuntimeError("Mock platform rejected the application")
        return SubmittedApplication(
            external_id=f"mock-application-{application_id}",
            status="SUBMITTED",
            message="Mock Platform accepted the application.",
        )

    async def get_application_status(self, *, external_id: str) -> str:
        return "SUBMITTED" if external_id.startswith("mock-application-") else "UNKNOWN"

    @staticmethod
    def _job(job) -> PlatformJob:
        return PlatformJob(
            id=job.id,
            title=job.title,
            location=job.location,
            description=job.description,
            platform=job.platform,
        )
