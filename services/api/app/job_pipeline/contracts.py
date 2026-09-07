from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RawJobRecord:
    source: str
    source_job_id: str | None
    source_url: str | None
    raw_title: str
    raw_salary: str | None
    raw_location: str | None
    description_html: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    collected_at: datetime | None = None
    company_name: str | None = None
    education: str | None = None
    experience: str | None = None
    employment_type: str | None = None


@dataclass(frozen=True)
class CleanedJobText:
    text: str
    removed_noise: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SectionItem:
    text: str
    section: str
    item_index: int
    line_index: int


@dataclass(frozen=True)
class EvidenceSpan:
    value: str
    evidence_text: str
    section: str
    item_index: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    confidence: float = 0.0
    valid: bool = False


@dataclass(frozen=True)
class JobPipelineResult:
    status: str
    canonical: dict[str, Any]
    quality_score: float
    quality_level: str
    warnings: tuple[str, ...] = ()
    stage_metrics: dict[str, int] = field(default_factory=dict)
    evidence: tuple[EvidenceSpan, ...] = ()
