from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.platforms.base import JobPlatformAdapter, PlatformAdapterError
from app.platforms.careerboard import CareerBoardAdapter
from app.platforms.mock import MockPlatformAdapter


class PlatformAdapterRegistry:
    """Resolve adapters without coupling BrowserTask logic to a platform."""

    def __init__(self, session: AsyncSession) -> None:
        self._adapters: dict[str, JobPlatformAdapter] = {
            "mock": MockPlatformAdapter(session),
            "careerboard": CareerBoardAdapter(session),
        }

    def get(self, platform: str) -> JobPlatformAdapter:
        adapter = self._adapters.get(platform.casefold())
        if adapter is None:
            raise PlatformAdapterError(f"Unsupported platform adapter: {platform}")
        return adapter

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "name": "mock",
                "label": "Mock Platform",
                "mode": "local_fixture",
                "safe_for_automation": True,
            },
            {
                "name": "careerboard",
                "label": "CareerBoard Prototype",
                "mode": "user_browser_session",
                "safe_for_automation": False,
            },
        ]
