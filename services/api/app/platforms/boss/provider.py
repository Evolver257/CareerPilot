from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.platforms.base import ProviderErrorCode, RecruitmentProviderError
from app.platforms.boss.detectors import ALLOWED_BOSS_HOSTS
from app.platforms.boss.parser import BossVisibleJob, parse_job_list
from app.platforms.domain import (
    JobReference,
    JobSearchQuery,
    NormalizedJob,
    ProviderCapabilities,
    ProviderHealth,
    ProviderSearchResult,
)
from app.platforms.location import split_location
from app.platforms.salary import parse_salary_text
from app.repositories.campaigns import CampaignRepository


class BossProvider:
    """Recruitment-data provider backed by visible BOSS page captures."""

    name = "boss"
    label = "BOSS 直聘"
    capabilities = ProviderCapabilities(
        district=True,
        salary=True,
        experience=True,
        education=True,
        job_type=True,
        search=True,
        detail=True,
    )

    def __init__(self, session) -> None:
        self.repository = CampaignRepository(session)

    def can_handle_url(self, url: str) -> bool:
        return (urlsplit(url).hostname or "").casefold() in ALLOWED_BOSS_HOSTS

    def extract_job_reference(self, url: str) -> JobReference:
        if not self.can_handle_url(url):
            raise RecruitmentProviderError(
                self.name,
                ProviderErrorCode.UNKNOWN,
                "URL 不是 BOSS 直聘地址",
                parser_stage="reference",
            )
        path_parts = [part for part in urlsplit(url).path.split("/") if part]
        try:
            index = path_parts.index("job_detail")
            external_id = path_parts[index + 1].split(".", 1)[0]
        except (ValueError, IndexError) as exc:
            raise RecruitmentProviderError(
                self.name,
                ProviderErrorCode.PARSER_FAILED,
                "无法从 BOSS 职位 URL 提取职位编号",
                parser_stage="reference",
                field="external_job_id",
            ) from exc
        return JobReference(self.name, external_id, url)

    def parse_search_result(self, raw_data: Any, *, page_url: str) -> list[NormalizedJob]:
        if isinstance(raw_data, str):
            try:
                visible_jobs = parse_job_list(raw_data, page_url=page_url)
            except Exception as exc:
                if isinstance(exc, RecruitmentProviderError):
                    raise
                raise RecruitmentProviderError(
                    self.name,
                    ProviderErrorCode.PARSER_FAILED,
                    "BOSS 搜索结果解析失败",
                    parser_stage="search",
                ) from exc
        elif isinstance(raw_data, list):
            visible_jobs = [item for item in raw_data if isinstance(item, BossVisibleJob)]
        else:
            raise RecruitmentProviderError(
                self.name,
                ProviderErrorCode.PARSER_FAILED,
                "BOSS 搜索结果不是可识别的页面数据",
                parser_stage="search",
            )
        return [self._visible_job(item) for item in visible_jobs]

    def parse_job_detail(self, raw_data: Any, *, reference: JobReference) -> NormalizedJob:
        jobs = self.parse_search_result(raw_data, page_url=reference.source_url)
        for job in jobs:
            if job.external_job_id == reference.external_job_id:
                return job
        if jobs:
            return jobs[0]
        raise RecruitmentProviderError(
            self.name,
            ProviderErrorCode.PARSER_FAILED,
            "BOSS 职位详情没有可识别内容",
            parser_stage="detail",
        )

    async def search_jobs(self, query: JobSearchQuery) -> ProviderSearchResult:
        jobs = await self.repository.search_jobs(
            keywords=[query.keyword] if query.keyword else [],
            cities=[value for value in (query.city, query.district) if value],
            limit=query.page_size,
            offset=(query.page - 1) * query.page_size,
            platform=self.name,
            salary_min=query.salary_min,
            salary_max=query.salary_max,
            education=list(query.education),
            experience=list(query.experience),
            job_types=list(query.job_type),
            industries=list(query.industry),
        )
        normalized = tuple(self._stored_job(job) for job in jobs)
        return ProviderSearchResult(
            jobs=normalized,
            health=ProviderHealth(
                platform=self.name,
                status="success",
                result_count=len(normalized),
                cards_found=len(normalized),
                cards_parsed=len(normalized),
            ),
        )

    async def get_job_detail(self, reference: JobReference) -> NormalizedJob | None:
        jobs = await self.repository.search_jobs(
            keywords=[], cities=[], limit=1000, platform=self.name
        )
        return next(
            (
                self._stored_job(job)
                for job in jobs
                if job.external_job_id == reference.external_job_id
            ),
            None,
        )

    @staticmethod
    def _visible_job(job: BossVisibleJob) -> NormalizedJob:
        location = split_location(job.location)
        salary = parse_salary_text(job.salary_text)
        return NormalizedJob(
            platform="boss",
            external_job_id=job.external_job_id,
            source_url=job.source_url,
            title=job.title,
            company_name=job.company_name,
            salary_text=salary.text or job.salary_text,
            salary_min=salary.minimum,
            salary_max=salary.maximum,
            salary_months=salary.months,
            city=location.city,
            district=location.district,
            location=location.location,
            description=job.description,
            raw_data={"description_source": "visible_page"},
        )

    @staticmethod
    def _stored_job(job) -> NormalizedJob:
        raw_data = job.raw_data or {}
        location = split_location(job.location)
        raw_salary = (
            raw_data.get("salary_text")
            if isinstance(raw_data.get("salary_text"), str)
            else None
        )
        salary = parse_salary_text(raw_salary)
        return NormalizedJob(
            id=job.id,
            platform=job.platform,
            external_job_id=job.external_job_id or str(job.id),
            source_url=job.source_url or "",
            title=job.title,
            company_name=(
                raw_data.get("company_name")
                if isinstance(raw_data.get("company_name"), str)
                else None
            ),
            salary_text=salary.text or raw_salary,
            salary_min=job.salary_min if job.salary_min is not None else salary.minimum,
            salary_max=job.salary_max if job.salary_max is not None else salary.maximum,
            salary_months=salary.months,
            city=location.city,
            district=location.district,
            location=location.location,
            experience=job.experience_requirement,
            education=job.education_requirement,
            job_type=job.job_type,
            description=job.description,
            raw_data=raw_data,
            platform_metadata=job.platform_metadata or {},
        )
