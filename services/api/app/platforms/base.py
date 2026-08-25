from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.schemas.browser import BrowserAction


class PlatformAdapterError(RuntimeError):
    """Base error raised by a platform adapter."""


class CaptchaRequiredError(PlatformAdapterError):
    """The platform requires a human to solve a CAPTCHA."""


class LoginRequiredError(PlatformAdapterError):
    """The platform requires a human login."""


class PlatformLimitError(PlatformAdapterError):
    """The platform has temporarily limited the account."""


class DomChangedError(PlatformAdapterError):
    """The expected page structure is no longer present."""


class RiskControlDetectedError(PlatformAdapterError):
    """The platform has presented a risk-control state to the user."""


class UnknownStateError(PlatformAdapterError):
    """The adapter cannot safely identify the current page state."""


@dataclass(frozen=True)
class PlatformJob:
    id: UUID
    title: str
    location: str | None
    description: str
    platform: str


@dataclass(frozen=True)
class PreparedApplication:
    actions: Sequence[BrowserAction]
    context: dict[str, Any]


@dataclass(frozen=True)
class SubmittedApplication:
    external_id: str
    status: str
    message: str


class JobPlatformAdapter(Protocol):
    name: str

    async def search_jobs(
        self, *, keywords: list[str], cities: list[str], limit: int
    ) -> list[PlatformJob]: ...

    async def get_job_detail(self, job_id: UUID) -> PlatformJob | None: ...

    async def normalize_job(self, job: PlatformJob) -> dict[str, Any]: ...

    async def prepare_application(
        self, *, application_id: UUID, scenario: str
    ) -> PreparedApplication: ...

    async def submit_application(
        self, *, application_id: UUID, scenario: str, observations: dict[str, Any]
    ) -> SubmittedApplication: ...

    async def get_application_status(self, *, external_id: str) -> str: ...
