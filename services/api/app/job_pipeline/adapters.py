from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from app.job_pipeline.contracts import RawJobRecord


class JobSourceAdapter(Protocol):
    source: str

    def to_raw_record(self, payload: Any) -> RawJobRecord: ...


class NormalizedJobSourceAdapter:
    """Bridge existing platform providers into the source-neutral ETL contract."""

    source = ""

    def to_raw_record(self, payload: Any) -> RawJobRecord:
        raw: Mapping[str, Any] = getattr(payload, "raw_data", None) or {}
        source = str(getattr(payload, "platform", None) or self.source)
        collected = getattr(payload, "crawled_at", None) or datetime.now(UTC)
        description = str(
            raw.get("description_html")
            or raw.get("raw_description")
            or getattr(payload, "description", "")
        )
        return RawJobRecord(
            source=source,
            source_job_id=str(getattr(payload, "external_job_id", "") or "") or None,
            source_url=str(getattr(payload, "source_url", "") or "") or None,
            raw_title=str(getattr(payload, "title", "") or ""),
            raw_salary=str(getattr(payload, "salary_text", "") or raw.get("salary_text") or "")
            or None,
            raw_location=str(getattr(payload, "location", "") or getattr(payload, "city", "") or "")
            or None,
            description_html=description,
            raw_payload=dict(raw),
            collected_at=collected,
            company_name=str(getattr(payload, "company_name", "") or raw.get("company_name") or "")
            or None,
            education=str(getattr(payload, "education", "") or raw.get("education") or "") or None,
            experience=str(getattr(payload, "experience", "") or raw.get("experience") or "")
            or None,
            employment_type=str(getattr(payload, "job_type", "") or raw.get("job_type") or "")
            or None,
        )


class BossJobSourceAdapter(NormalizedJobSourceAdapter):
    source = "boss"


class ZhaopinJobSourceAdapter(NormalizedJobSourceAdapter):
    source = "zhaopin"


ADAPTERS: dict[str, JobSourceAdapter] = {
    "boss": BossJobSourceAdapter(),
    "zhaopin": ZhaopinJobSourceAdapter(),
}


def get_source_adapter(source: str) -> JobSourceAdapter:
    return ADAPTERS.get(source.casefold(), NormalizedJobSourceAdapter())
