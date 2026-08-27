from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

RetrievalMode = Literal["hybrid", "full_text", "vector"]


class JobKnowledgeFilters(BaseModel):
    cities: list[str] = Field(default_factory=list, max_length=20)
    education: str | None = Field(default=None, max_length=100)
    experience: str | None = Field(default=None, max_length=100)
    job_types: list[str] = Field(default_factory=list, max_length=10)
    platform: str | None = Field(default=None, max_length=100)
    salary_floor: int | None = Field(default=None, ge=0)
    salary_ceiling: int | None = Field(default=None, ge=0)
    published_after: datetime | None = None
    published_before: datetime | None = None


class JobKnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)
    retrieval_mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=10, ge=1, le=50)
    full_text_top_k: int = Field(default=100, ge=1, le=300)
    vector_top_k: int = Field(default=100, ge=1, le=300)
    resume_id: UUID | None = None
    include_resume_evidence: bool = False
    force_refresh: bool = False


class KnowledgeDistributionItem(BaseModel):
    label: str
    count: int
    percentage: float


class KnowledgeSalaryBand(BaseModel):
    unit: str
    unit_label: str
    sample_count: int
    minimum: float
    p25: float
    median: float
    p75: float
    maximum: float


class KnowledgeSkillDemand(BaseModel):
    name: str
    category: str
    count: int
    percentage: float
    required_count: int
    preferred_count: int
    inferred_count: int
    job_ids: list[UUID] = Field(default_factory=list)


class JobKnowledgeStatistics(BaseModel):
    sample_count: int
    data_as_of: datetime | None = None
    salary_bands: list[KnowledgeSalaryBand] = Field(default_factory=list)
    education_distribution: list[KnowledgeDistributionItem] = Field(default_factory=list)
    experience_distribution: list[KnowledgeDistributionItem] = Field(default_factory=list)
    skills: list[KnowledgeSkillDemand] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class JobKnowledgeCitation(BaseModel):
    citation_index: int
    job_id: UUID
    chunk_id: UUID
    title: str
    company: str | None = None
    location: str | None = None
    platform: str
    source_url: str | None = None
    section_type: str
    evidence: str
    retrieval_sources: list[str] = Field(default_factory=list)
    lexical_score: float = Field(ge=0, le=100)
    semantic_score: float = Field(ge=0, le=100)
    fusion_score: float = Field(ge=0, le=100)
    rank: int = Field(ge=1)


class ResumeKnowledgeEvidence(BaseModel):
    job_id: UUID
    chunk_id: UUID
    chunk_type: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    rerank_score: float


class JobKnowledgeSearchResponse(BaseModel):
    query: str
    retrieval_mode: RetrievalMode
    knowledge_version: str
    cache_hit: bool = False
    generated_at: datetime
    data_as_of: datetime | None = None
    sample_count: int
    filters: JobKnowledgeFilters
    statistics: JobKnowledgeStatistics
    citations: list[JobKnowledgeCitation] = Field(default_factory=list)
    resume_evidence: list[ResumeKnowledgeEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
