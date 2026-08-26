from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.platforms.base import (
    CaptchaRequiredError,
    DomChangedError,
    JobPlatformAdapter,
    LoginRequiredError,
    PlatformJob,
    PlatformLimitError,
    PreparedApplication,
    RiskControlDetectedError,
    SubmittedApplication,
    UnknownStateError,
)
from app.platforms.boss.actions import build_application_actions
from app.platforms.boss.detectors import BossPageSnapshot, detector, is_boss_url
from app.platforms.boss.parser import parse_job_list
from app.repositories.campaigns import CampaignRepository


class BossZhipinAdapter(JobPlatformAdapter):
    """User-visible BOSS adapter; it never fetches the site itself."""

    name = "boss"

    def __init__(self, session: AsyncSession) -> None:
        self.repository = CampaignRepository(session)

    async def search_jobs(
        self, *, keywords: list[str], cities: list[str], limit: int
    ) -> list[PlatformJob]:
        jobs = await self.repository.search_jobs(keywords=keywords, cities=cities, limit=limit)
        return [self._job(job) for job in jobs if job.platform == self.name]

    async def get_job_detail(self, job_id: UUID) -> PlatformJob | None:
        jobs = await self.repository.search_jobs(keywords=[], cities=[], limit=300)
        return next(
            (self._job(job) for job in jobs if job.id == job_id and job.platform == self.name),
            None,
        )

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
        source_url = application.job.source_url
        if not is_boss_url(source_url):
            raise UnknownStateError("BOSS application has no approved zhipin.com source URL")
        return PreparedApplication(
            actions=build_application_actions(source_url=source_url),
            context={
                "application_id": str(application.id),
                "job_id": str(application.job_id),
                "external_job_id": application.job.external_job_id,
                "source_url": source_url,
                "scenario": scenario.upper(),
                "adapter": self.name,
                "credential_boundary": "user_browser_session_only",
                "user_confirmation_required": True,
            },
        )

    async def submit_application(
        self, *, application_id: UUID, scenario: str, observations: dict[str, object]
    ) -> SubmittedApplication:
        scenario_name = scenario.upper()
        scenario_errors = {
            "CAPTCHA_REQUIRED": CaptchaRequiredError("BOSS CAPTCHA requires user action"),
            "LOGIN_REQUIRED": LoginRequiredError("BOSS login is required"),
            "PLATFORM_LIMIT": PlatformLimitError("BOSS platform limit requires user action"),
            "RISK_CONTROL": RiskControlDetectedError("BOSS risk control requires user action"),
            "DOM_CHANGED": DomChangedError("BOSS DOM changed; user review is required"),
            "UNKNOWN_STATE": UnknownStateError(
                "BOSS page state is unknown; user review is required"
            ),
        }
        if scenario_name in scenario_errors:
            raise scenario_errors[scenario_name]
        snapshot = self._snapshot(observations)
        detector.detect(snapshot)
        if not self._communication_completed(observations):
            raise DomChangedError(
                "BOSS immediate communication button was not confirmed as clicked"
            )
        return SubmittedApplication(
            external_id=f"boss-application-{application_id}",
            status="SUBMITTED",
            message="BOSS user-confirmed browser action completed; final state is recorded.",
        )

    async def get_application_status(self, *, external_id: str) -> str:
        return "SUBMITTED" if external_id.startswith("boss-application-") else "UNKNOWN"

    @staticmethod
    def parse_job_snapshot(html: str, *, page_url: str):
        return parse_job_list(html, page_url=page_url)

    @staticmethod
    def _snapshot(observations: dict[str, object]) -> BossPageSnapshot:
        text_parts: list[str] = []
        html_parts: list[str] = []
        title_parts: list[str] = []
        urls: list[str] = []
        for value in observations.values():
            if not isinstance(value, dict):
                continue
            data = value.get("data")
            if isinstance(data, dict):
                for key, target in (("text", text_parts), ("html", html_parts)):
                    item = data.get(key)
                    if isinstance(item, str):
                        target.append(item)
                page_url = data.get("page_url") or data.get("url")
                if isinstance(page_url, str):
                    urls.append(page_url)
            page_state = value.get("page_state")
            if isinstance(page_state, str):
                title_parts.append(page_state)
        return BossPageSnapshot(
            html="\n".join(html_parts),
            text="\n".join(text_parts),
            title="\n".join(title_parts),
            url=urls[-1] if urls else None,
        )

    @staticmethod
    def _communication_completed(observations: dict[str, object]) -> bool:
        accepted = {"started", "already_contacted"}
        for value in observations.values():
            if not isinstance(value, dict):
                continue
            data = value.get("data")
            if not isinstance(data, dict):
                continue
            if (
                data.get("boss_action") == "immediate_communication"
                and data.get("communication_status") in accepted
            ):
                return True
        return False

    @staticmethod
    def _job(job) -> PlatformJob:
        return PlatformJob(
            id=job.id,
            title=job.title,
            location=job.location,
            description=job.description,
            platform="boss",
        )
