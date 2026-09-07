from __future__ import annotations

from collections.abc import Iterable

from app.platforms.domain import RecruitmentProvider


class PlatformResolver:
    def __init__(self, providers: Iterable[RecruitmentProvider] = ()) -> None:
        self._providers = tuple(providers)

    def resolve(self, url: str) -> str | None:
        for provider in self._providers:
            if provider.can_handle_url(url):
                return provider.name
        return None

    def provider_for(self, url: str) -> RecruitmentProvider | None:
        for provider in self._providers:
            if provider.can_handle_url(url):
                return provider
        return None
