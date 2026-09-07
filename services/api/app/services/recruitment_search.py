from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.platforms.base import PlatformAdapterError, RecruitmentProviderError
from app.platforms.domain import JobSearchQuery, NormalizedJob, ProviderHealth
from app.platforms.fingerprint import job_fingerprint
from app.platforms.registry import RecruitmentProviderRegistry


@dataclass(frozen=True)
class AggregatedRecruitmentSearch:
    jobs: tuple[NormalizedJob, ...]
    platform_status: dict[str, ProviderHealth]
    possible_duplicate_count: int = 0


class RecruitmentSearchService:
    """Coordinate provider searches while keeping provider failures isolated."""

    def __init__(
        self,
        session: AsyncSession,
        registry: RecruitmentProviderRegistry | None = None,
    ) -> None:
        self.registry = registry or RecruitmentProviderRegistry(session)

    async def search(self, query: JobSearchQuery) -> AggregatedRecruitmentSearch:
        platform_names = query.normalized_platforms or tuple(
            item["id"] for item in self.registry.catalog()
        )
        jobs: list[NormalizedJob] = []
        statuses: dict[str, ProviderHealth] = {}
        seen_platform_ids: set[tuple[str, str]] = set()

        # A single AsyncSession cannot safely run concurrent DB operations. The
        # provider boundary stays async so a future per-provider session pool can
        # parallelize this loop without changing the API contract.
        for platform_name in platform_names:
            started = perf_counter()
            try:
                provider = self.registry.get(platform_name)
                result = await provider.search_jobs(query)
                for job in result.jobs:
                    key = (job.platform, job.external_job_id)
                    if key in seen_platform_ids:
                        continue
                    seen_platform_ids.add(key)
                    jobs.append(job)
                statuses[platform_name] = _with_duration(
                    result.health, started=started
                )
            except RecruitmentProviderError as exc:
                statuses[platform_name] = ProviderHealth(
                    platform=platform_name,
                    status="error",
                    error_code=exc.code.value,
                    message=exc.message,
                    duration_ms=_duration_ms(started),
                )
            except PlatformAdapterError as exc:
                statuses[platform_name] = ProviderHealth(
                    platform=platform_name,
                    status="error",
                    error_code="UNKNOWN",
                    message=str(exc),
                    duration_ms=_duration_ms(started),
                )
            except Exception as exc:  # provider isolation is an API boundary
                statuses[platform_name] = ProviderHealth(
                    platform=platform_name,
                    status="error",
                    error_code="UNKNOWN",
                    message=str(exc),
                    duration_ms=_duration_ms(started),
                )

        fingerprint_groups: dict[str, int] = {}
        for job in jobs:
            fingerprint = job_fingerprint(
                company_name=job.company_name,
                title=job.title,
                city=job.city,
            )
            if fingerprint:
                fingerprint_groups[fingerprint] = fingerprint_groups.get(fingerprint, 0) + 1
        possible_duplicates = sum(
            count - 1 for count in fingerprint_groups.values() if count > 1
        )
        return AggregatedRecruitmentSearch(
            jobs=tuple(jobs),
            platform_status=statuses,
            possible_duplicate_count=possible_duplicates,
        )


def _duration_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _with_duration(health: ProviderHealth, *, started: float) -> ProviderHealth:
    if health.duration_ms is not None:
        return health
    return ProviderHealth(
        platform=health.platform,
        status=health.status,
        result_count=health.result_count,
        cards_found=health.cards_found,
        cards_parsed=health.cards_parsed,
        parse_failure_count=health.parse_failure_count,
        error_code=health.error_code,
        message=health.message,
        duration_ms=_duration_ms(started),
    )
