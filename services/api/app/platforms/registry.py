from __future__ import annotations

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.platforms.base import JobPlatformAdapter, PlatformAdapterError
from app.platforms.boss import BossZhipinAdapter
from app.platforms.boss.provider import BossProvider
from app.platforms.careerboard import CareerBoardAdapter
from app.platforms.domain import RecruitmentProvider
from app.platforms.mock import MockPlatformAdapter
from app.platforms.resolver import PlatformResolver
from app.platforms.zhaopin.adapter import ZhaopinAdapter


class PlatformAdapterRegistry:
    """Resolve adapters without coupling BrowserTask logic to a platform."""

    def __init__(self, session: AsyncSession) -> None:
        self._adapters: dict[str, JobPlatformAdapter] = {
            "mock": MockPlatformAdapter(session),
            "careerboard": CareerBoardAdapter(session),
            "boss": BossZhipinAdapter(session),
            "zhaopin": ZhaopinAdapter(session),
        }

    def get(self, platform: str) -> JobPlatformAdapter:
        adapter = self._adapters.get(platform.casefold())
        if adapter is None:
            raise PlatformAdapterError(f"Unsupported platform adapter: {platform}")
        return adapter

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "name": "zhaopin",
                "label": "智联招聘 · 立即投递",
                "mode": "user_browser_session",
                "safe_for_automation": False,
            },
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
            {
                "name": "boss",
                "label": "BOSS 直聘 · 可见页面兼容",
                "mode": "user_browser_session",
                "safe_for_automation": False,
            },
        ]


class RecruitmentProviderRegistry:
    """Registry for search/detail providers, separate from submission adapters."""

    def __init__(self, session: AsyncSession) -> None:
        from app.platforms.zhaopin.provider import ZhaopinProvider

        self._providers: dict[str, RecruitmentProvider] = {}
        for provider in (BossProvider(session), ZhaopinProvider(session)):
            self.register(provider)

    def register(self, provider: RecruitmentProvider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"Recruitment provider already registered: {provider.name}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> RecruitmentProvider:
        try:
            return self._providers[name.casefold()]
        except KeyError as exc:
            raise PlatformAdapterError(f"Unsupported recruitment provider: {name}") from exc

    def resolve_by_url(self, url: str) -> RecruitmentProvider | None:
        return PlatformResolver(self._providers.values()).provider_for(url)

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "id": provider.name,
                "name": provider.label,
                "enabled": True,
                "capabilities": asdict(provider.capabilities),
                "browser_session_required": provider.capabilities.browser_session_required,
            }
            for provider in self._providers.values()
        ]
