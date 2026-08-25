from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platforms.base import (
    JobPlatformAdapter,
    PlatformJob,
    PreparedApplication,
    SubmittedApplication,
    UnknownStateError,
)
from app.platforms.careerboard.actions import build_application_actions
from app.platforms.careerboard.detectors import PageSnapshot, detector
from app.platforms.careerboard.parser import parse_job_detail
from app.repositories.campaigns import CampaignRepository


class CareerBoardAdapter(JobPlatformAdapter):
    """Safe CareerBoard adapter prototype for an already-open user browser.

    The default URL is the local CareerPilot fixture. A deployment may provide
    another user-visible URL, but this adapter never performs HTTP requests or
    receives credentials, cookies, or authentication tokens.
    """

    name = "careerboard"

    def __init__(self, session: AsyncSession, *, base_url: str = "http://localhost:3000") -> None:
        self.repository = CampaignRepository(session)
        self.base_url = base_url.rstrip("/")

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
            "platform": self.name,
        }

    async def prepare_application(
        self, *, application_id: UUID, scenario: str
    ) -> PreparedApplication:
        application = await self.repository.get_application(application_id)
        if application is None:
            raise ValueError("Application not found")
        actions = build_application_actions(job_id=application.job_id, base_url=self.base_url)
        return PreparedApplication(
            actions=actions,
            context={
                "application_id": str(application.id),
                "job_id": str(application.job_id),
                "scenario": scenario.upper(),
                "adapter": self.name,
                "credential_boundary": "user_browser_session_only",
            },
        )

    async def submit_application(
        self, *, application_id: UUID, scenario: str, observations: dict[str, object]
    ) -> SubmittedApplication:
        scenario_name = scenario.upper()
        if scenario_name in {"DOM_CHANGED", "UNKNOWN_STATE"}:
            raise UnknownStateError("CareerBoard DOM/state changed; user review is required")
        if scenario_name in {"CAPTCHA_REQUIRED", "LOGIN_REQUIRED", "RISK_CONTROL"}:
            # The corresponding detector is exercised by the snapshot below in
            # real browser sessions; scenario mapping keeps CI deterministic.
            self._raise_scenario_state(scenario_name)

        snapshot = self._snapshot(observations)
        if snapshot.html or snapshot.text or snapshot.title:
            detector.detect(snapshot)
        elif scenario_name != "SUCCESS":
            raise UnknownStateError("CareerBoard returned no inspectable page snapshot")
        return SubmittedApplication(
            external_id=f"careerboard-application-{application_id}",
            status="SUBMITTED",
            message="CareerBoard prototype accepted the user-confirmed browser action.",
        )

    async def get_application_status(self, *, external_id: str) -> str:
        return "SUBMITTED" if external_id.startswith("careerboard-application-") else "UNKNOWN"

    @staticmethod
    def parse_job_snapshot(html: str, *, job_id: UUID) -> PlatformJob:
        return parse_job_detail(html, job_id=job_id, platform="careerboard")

    @staticmethod
    def _snapshot(observations: dict[str, object]) -> PageSnapshot:
        text_parts: list[str] = []
        html_parts: list[str] = []
        title_parts: list[str] = []
        for value in observations.values():
            if not isinstance(value, dict):
                continue
            data = value.get("data")
            if isinstance(data, dict):
                for key, target in (("text", text_parts), ("html", html_parts)):
                    item = data.get(key)
                    if isinstance(item, str):
                        target.append(item)
            page_state = value.get("page_state")
            if isinstance(page_state, str):
                title_parts.append(page_state)
        return PageSnapshot(
            html="\n".join(html_parts),
            text="\n".join(text_parts),
            title="\n".join(title_parts),
        )

    @staticmethod
    def _raise_scenario_state(scenario: str) -> None:
        from app.platforms.base import (
            CaptchaRequiredError,
            LoginRequiredError,
            RiskControlDetectedError,
        )

        errors = {
            "CAPTCHA_REQUIRED": CaptchaRequiredError("CareerBoard CAPTCHA requires user action"),
            "LOGIN_REQUIRED": LoginRequiredError("CareerBoard login is required"),
            "RISK_CONTROL": RiskControlDetectedError(
                "CareerBoard risk control requires user action"
            ),
        }
        raise errors[scenario]

    @staticmethod
    def _job(job) -> PlatformJob:
        return PlatformJob(
            id=job.id,
            title=job.title,
            location=job.location,
            description=job.description,
            platform="careerboard",
        )
