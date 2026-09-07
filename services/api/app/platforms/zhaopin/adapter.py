from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from app.platforms.base import (
    CaptchaRequiredError,
    DomChangedError,
    LoginRequiredError,
    PlatformJob,
    PlatformLimitError,
    PreparedApplication,
    RiskControlDetectedError,
    SubmittedApplication,
    UnknownStateError,
)
from app.platforms.boss.adapter import BossZhipinAdapter
from app.platforms.zhaopin.detectors import ZHAOPIN_HOSTS
from app.schemas.browser import BrowserAction, BrowserTarget


def detail_id(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value or "")
        if (
            url.scheme != "https"
            or url.hostname not in ZHAOPIN_HOSTS
            or url.username
            or url.password
            or url.port not in (None, 443)
        ):
            return None
        match = re.fullmatch(r"/(?:jobdetail|jobs|job|position|zw)/([\w-]+)\.html?", url.path, re.I)
        return match.group(1) if match else None
    except ValueError:
        return None


class ZhaopinAdapter(BossZhipinAdapter):
    """Reuse repository lookups, not BOSS parsing or submission semantics."""

    name = "zhaopin"

    async def prepare_application(
        self, *, application_id: UUID, scenario: str
    ) -> PreparedApplication:
        application = await self.repository.get_application(application_id)
        if application is None or application.platform != self.name:
            raise UnknownStateError("智联投递记录不存在或平台不匹配")
        source = application.job.source_url
        job_id = detail_id(source)
        if not job_id or job_id != application.job.external_job_id:
            raise UnknownStateError("智联岗位原页无效或职位 ID 不匹配，请重新采集")
        parsed = urlsplit(source)
        query = urlencode([(key, value) for key, value in parse_qsl(parsed.query) if key != "task"])
        task_url = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                f"{query + '&' if query else ''}task={{task_id}}",
                parsed.fragment,
            )
        )
        metadata = {
            "platform": self.name,
            "expected_job_id": job_id,
            "mode": "zhaopin_immediate_apply",
        }
        return PreparedApplication(
            actions=[
                BrowserAction(action="NAVIGATE", url=task_url),
                BrowserAction(action="CHECK_STATE", metadata=metadata),
                BrowserAction(
                    action="CLICK",
                    target=BrowserTarget(strategy="zhaopin-semantic", name="立即投递"),
                    metadata={
                        **metadata,
                        "requires_user_approval": True,
                        "external_side_effect": "application",
                    },
                ),
                BrowserAction(action="EXTRACT", metadata=metadata),
            ],
            context={
                "adapter": self.name,
                "source_url": source,
                "external_job_id": job_id,
                "credential_boundary": "user_browser_session_only",
                "user_confirmation_required": True,
            },
        )

    async def submit_application(
        self, *, application_id: UUID, scenario: str, observations: dict[str, object]
    ) -> SubmittedApplication:
        application = await self.repository.get_application(application_id)
        if application is None or application.platform != self.name:
            raise UnknownStateError("投递记录不存在")
        errors = {
            "CAPTCHA": CaptchaRequiredError,
            "CAPTCHA_REQUIRED": CaptchaRequiredError,
            "LOGIN_REQUIRED": LoginRequiredError,
            "RISK_CONTROL": RiskControlDetectedError,
            "PLATFORM_LIMIT": PlatformLimitError,
            "DOM_CHANGED": DomChangedError,
            "UNKNOWN_STATE": UnknownStateError,
        }
        if scenario.upper() in errors:
            raise errors[scenario.upper()]("智联页面需要人工处理")
        for observation in reversed(list(observations.values())):
            if not isinstance(observation, dict):
                continue
            data = observation.get("data", {})
            if not isinstance(data, dict) or data.get("zhaopin_action") != "immediate_apply":
                continue
            state = observation.get("page_state")
            if state in errors:
                raise errors[state]("智联页面需要人工处理")
            if (
                state == "READY"
                and observation.get("success") is True
                and data.get("application_status") in {"submitted", "already_applied"}
                and data.get("confirmation") in {"success_notice", "applied_button"}
                and detail_id(data.get("page_url")) == application.job.external_job_id
            ):
                return SubmittedApplication(
                    external_id=f"zhaopin-application-{application_id}",
                    status="SUBMITTED",
                    message="智联岗位页面已确认投递成功或已投递",
                )
            raise UnknownStateError("未确认智联投递结果，请在岗位原页核验；不要重复投递")
        raise UnknownStateError("缺少智联投递确认结果")

    async def get_application_status(self, *, external_id: str) -> str:
        return "SUBMITTED" if external_id.startswith("zhaopin-application-") else "UNKNOWN"

    @staticmethod
    def _job(job) -> PlatformJob:
        return PlatformJob(
            id=job.id,
            title=job.title,
            location=job.location,
            description=job.description,
            platform="zhaopin",
        )
