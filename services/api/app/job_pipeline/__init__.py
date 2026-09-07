"""Deterministic ETL primitives for turning scraped jobs into trusted knowledge."""

from app.job_pipeline.adapters import (
    BossJobSourceAdapter,
    JobSourceAdapter,
    ZhaopinJobSourceAdapter,
    get_source_adapter,
)
from app.job_pipeline.contracts import (
    CleanedJobText,
    EvidenceSpan,
    JobPipelineResult,
    RawJobRecord,
    SectionItem,
)
from app.job_pipeline.pipeline import JobETLPipeline

__all__ = [
    "CleanedJobText",
    "BossJobSourceAdapter",
    "EvidenceSpan",
    "JobSourceAdapter",
    "JobETLPipeline",
    "JobPipelineResult",
    "RawJobRecord",
    "SectionItem",
    "ZhaopinJobSourceAdapter",
    "get_source_adapter",
]
