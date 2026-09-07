from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.platforms.base import ProviderErrorCode, RecruitmentProviderError
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
from app.platforms.zhaopin.detectors import ZHAOPIN_HOSTS
from app.platforms.zhaopin.parser import ZhaopinRawJob, parse_zhaopin_payload
from app.repositories.campaigns import CampaignRepository


class ZhaopinProvider:
    """智联招聘 visible-page provider.

    Network/session acquisition remains in the browser extension. The backend
    owns safe parsing, normalization and persistence only.
    """

    name = "zhaopin"
    label = "智联招聘"
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
        return (urlsplit(url).hostname or "").casefold() in ZHAOPIN_HOSTS

    def extract_job_reference(self, url: str) -> JobReference:
        if not self.can_handle_url(url):
            raise RecruitmentProviderError(
                self.name,
                ProviderErrorCode.UNKNOWN,
                "URL 不是智联招聘地址",
                parser_stage="reference",
            )
        path = urlsplit(url).path
        parts = [part for part in path.split("/") if part]
        external_id = None
        for marker in ("jobdetail", "jobs", "job", "position", "zw"):
            if marker in parts:
                index = parts.index(marker)
                if index + 1 < len(parts):
                    external_id = parts[index + 1].split(".", 1)[0]
                    break
        if not external_id:
            query = dict(
                item.split("=", 1)
                for item in urlsplit(url).query.split("&")
                if "=" in item
            )
            external_id = query.get("jobId") or query.get("positionId")
        if not external_id:
            raise RecruitmentProviderError(
                self.name,
                ProviderErrorCode.PARSER_FAILED,
                "无法从智联招聘职位 URL 提取职位编号",
                parser_stage="reference",
                field="external_job_id",
            )
        return JobReference(self.name, external_id, url)

    def parse_search_result(self, raw_data: Any, *, page_url: str) -> list[NormalizedJob]:
        return [
            self._normalize(item, page_url=page_url)
            for item in parse_zhaopin_payload(raw_data, page_url=page_url)
        ]

    def parse_job_detail(self, raw_data: Any, *, reference: JobReference) -> NormalizedJob:
        jobs = self.parse_search_result(raw_data, page_url=reference.source_url)
        for job in jobs:
            if job.external_job_id == reference.external_job_id:
                return job
        raise RecruitmentProviderError(
            self.name,
            ProviderErrorCode.PARSER_FAILED,
            "智联招聘职位详情没有可识别内容",
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

    @classmethod
    def _normalize(cls, item: ZhaopinRawJob, *, page_url: str) -> NormalizedJob:
        location = split_location(item.location)
        salary = parse_salary_text(item.salary_text)
        # The extension keeps extraction provenance under raw_data. Flatten it
        # into the stored metadata without persisting a page HTML snapshot.
        extraction = item.raw_data.get("raw_data", {})
        extraction = extraction if isinstance(extraction, dict) else {}
        description_source = extraction.get("description_source", "provider")
        return NormalizedJob(
            platform=cls.name,
            external_job_id=item.external_job_id,
            source_url=item.source_url or page_url,
            title=item.title,
            company_name=item.company_name,
            salary_text=salary.text or item.salary_text,
            salary_min=salary.minimum,
            salary_max=salary.maximum,
            salary_months=salary.months,
            city=location.city,
            district=location.district,
            location=location.location,
            experience=normalize_experience(item.experience),
            education=normalize_education(item.education),
            description=item.description,
            requirements=item.requirements,
            skills=item.skills,
            benefits=item.benefits,
            raw_data={**item.raw_data, **extraction, "description_source": description_source},
            platform_metadata={
                "source": "zhaopin_visible_page",
                "description_source": description_source,
                "parser_version": extraction.get("parser_version"),
                "detail_url": extraction.get("detail_url"),
            },
        )

    @staticmethod
    def _stored_job(job) -> NormalizedJob:
        location = split_location(job.location)
        raw_data = job.raw_data or {}
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
            salary_text=(
                raw_data.get("salary_text")
                if isinstance(raw_data.get("salary_text"), str)
                else None
            ),
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            city=location.city,
            district=location.district,
            location=job.location,
            experience=job.experience_requirement,
            education=job.education_requirement,
            job_type=job.job_type,
            description=job.description,
            raw_data=raw_data,
            platform_metadata=job.platform_metadata or {},
        )


def normalize_education(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    if not text:
        return None
    for label in ("博士", "硕士", "研究生", "本科", "大专", "专科", "高中", "中专"):
        if label in text:
            return label
    if "不限" in text or "无要求" in text:
        return "不限"
    return text


def normalize_experience(value: str | None) -> str | None:
    text = " ".join((value or "").split())
    if not text:
        return None
    if "不限" in text or "无经验" in text:
        return "经验不限"
    if "应届" in text or "在校" in text:
        return "应届/在校生"
    return text
