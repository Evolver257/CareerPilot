from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MarketInsightCreate(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    mode: Literal["fast", "llm"] = "fast"
    cities: list[str] = Field(default_factory=list, max_length=10)
    job_types: list[str] = Field(default_factory=list, max_length=10)
    max_jobs: int = Field(default=50, ge=5, le=100)
    force: bool = False


class DistributionItem(BaseModel):
    label: str
    count: int
    percentage: float


class SalaryBand(BaseModel):
    unit: str
    unit_label: str
    sample_count: int
    minimum: float
    p25: float
    median: float
    p75: float
    maximum: float


class SkillInsight(BaseModel):
    name: str
    count: int
    percentage: float
    required_count: int
    preferred_count: int
    category: Literal["core", "high_frequency", "bonus", "emerging"]
    job_ids: list[UUID] = Field(default_factory=list)


class ResponsibilityTheme(BaseModel):
    name: str
    count: int
    percentage: float
    examples: list[str] = Field(default_factory=list)
    job_ids: list[UUID] = Field(default_factory=list)


class RoleCluster(BaseModel):
    name: str
    count: int
    percentage: float
    titles: list[str] = Field(default_factory=list)


class LearningPhase(BaseModel):
    weeks: str
    title: str
    objectives: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class EvidenceJob(BaseModel):
    id: UUID
    title: str
    company: str | None = None
    location: str | None = None
    salary_text: str | None = None
    education: str | None = None
    experience: str | None = None
    source_url: str | None = None
    relevance: float


class MarketInsightResult(BaseModel):
    query: str
    generated_at: datetime
    data_as_of: datetime | None = None
    sample_count: int
    confidence: str
    warnings: list[str] = Field(default_factory=list)
    salary_bands: list[SalaryBand] = Field(default_factory=list)
    education_distribution: list[DistributionItem] = Field(default_factory=list)
    experience_distribution: list[DistributionItem] = Field(default_factory=list)
    skills: list[SkillInsight] = Field(default_factory=list)
    responsibility_themes: list[ResponsibilityTheme] = Field(default_factory=list)
    role_clusters: list[RoleCluster] = Field(default_factory=list)
    learning_roadmap: list[LearningPhase] = Field(default_factory=list)
    summary_markdown: str = ""
    source_jobs: list[EvidenceJob] = Field(default_factory=list)
    llm_source: str = "deterministic"


class RoadmapAdjustment(BaseModel):
    weeks: str = Field(default="", max_length=30)
    focus: str = Field(default="", max_length=240)
    add_skills: list[str] = Field(default_factory=list, max_length=5)


class MarketInsightLLMOutput(BaseModel):
    summary_markdown: str = Field(default="", max_length=1800)
    learning_priorities: list[str] = Field(default_factory=list, max_length=5)
    roadmap_adjustments: list[RoadmapAdjustment] = Field(default_factory=list, max_length=5)


class MarketInsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    query: str
    mode: str
    status: str
    stage: str
    progress: int
    sample_count: int
    confidence: str
    fingerprint: str
    request: dict[str, Any]
    report: MarketInsightResult | None
    source_job_ids: list[UUID]
    llm_source: str
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cached: bool = False


class MarketInsightListResponse(BaseModel):
    items: list[MarketInsightRead]
    total: int
