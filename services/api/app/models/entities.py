from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.models.base import Base
from app.models.embedding import EmbeddingType


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    llm_active_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)

    preferences: Mapped[UserPreference | None] = relationship(back_populates="user", uselist=False)
    resumes: Mapped[list[Resume]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list[Campaign]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    llm_credentials: Mapped[list[LLMProviderCredential]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    browser_tasks: Mapped[list[BrowserTask]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    market_insight_reports: Mapped[list[MarketInsightReport]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    career_advisor_sessions: Mapped[list[CareerAdvisorSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memory_settings: Mapped[AgentMemorySetting | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    agent_memories: Mapped[list[AgentMemory]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    memory_candidates: Mapped[list[MemoryCandidate]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    mcp_connections: Mapped[list[MCPConnection]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    target_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_cities: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_companies: Mapped[list[str]] = mapped_column(JSON, default=list)
    blocked_companies: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    excluded_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    internship_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remote_preference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    min_match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="preferences")


class LLMProviderCredential(Base):
    __tablename__ = "llm_provider_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_llm_provider_credentials_user_provider"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    model: Mapped[str] = mapped_column(String(200), default="")
    base_url: Mapped[str] = mapped_column(String(2000), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    api_key_hint: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="llm_credentials")


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    structured_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="resumes")
    chunks: Mapped[list[ResumeChunk]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )
    scores: Mapped[list[JobScore]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )
    ranking_runs: Mapped[list[RankingRun]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )
    campaigns: Mapped[list[Campaign]] = relationship(back_populates="resume")
    applications: Mapped[list[Application]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class ResumeChunk(Base):
    __tablename__ = "resume_chunks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    resume_id: Mapped[UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"))
    chunk_type: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[str] = mapped_column(Text)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    resume: Mapped[Resume] = relationship(back_populates="chunks")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="company")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("platform", "external_job_id", name="uq_jobs_platform_external_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(100), index=True)
    external_job_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    company_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    education_requirement: Mapped[str | None] = mapped_column(String(500), nullable=True)
    experience_requirement: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    platform_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalized_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    job_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    data_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    data_quality_level: Mapped[str] = mapped_column(String(20), default="unknown", index=True)
    duplicate_group_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    last_collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    company: Mapped[Company | None] = relationship(back_populates="jobs")
    skills: Mapped[list[JobSkill]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    scores: Mapped[list[JobScore]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    campaign_jobs: Mapped[list[CampaignJob]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    versions: Mapped[list[JobVersion]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    knowledge_documents: Mapped[list[JobKnowledgeDocument]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    knowledge_chunks: Mapped[list[JobKnowledgeChunk]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    skill_facts: Mapped[list[JobSkillFact]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    requirements: Mapped[list[JobRequirement]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    career_advisor_links: Mapped[list[CareerAdvisorSessionJob]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    raw_snapshots: Mapped[list[RawJobSnapshot]] = relationship(
        back_populates="job", passive_deletes=True
    )


class RawJobSnapshot(Base):
    """Immutable source payload retained for ETL replay and parser debugging."""

    __tablename__ = "job_raw_snapshots"
    __table_args__ = (
        UniqueConstraint("job_id", "content_hash", name="uq_job_raw_snapshots_job_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_platform: Mapped[str] = mapped_column(String(100), index=True)
    external_job_id: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    raw_title: Mapped[str] = mapped_column(String(300), default="")
    raw_salary: Mapped[str | None] = mapped_column(String(300), nullable=True)
    raw_location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description_html: Mapped[str] = mapped_column(Text, default="")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job | None] = relationship(back_populates="raw_snapshots")


class JobSkill(Base):
    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint("job_id", "skill_name", "skill_type", name="uq_job_skills_name_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    skill_name: Mapped[str] = mapped_column(String(120), index=True)
    skill_type: Mapped[str] = mapped_column(String(30), index=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job] = relationship(back_populates="skills")


class JobRequirement(Base):
    """One atomic, source-backed requirement extracted from a JD."""

    __tablename__ = "job_requirements"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    requirement_type: Mapped[str] = mapped_column(String(40), index=True)
    normalized_value: Mapped[str] = mapped_column(String(300), index=True)
    source_text: Mapped[str] = mapped_column(Text, default="")
    source_section: Mapped[str] = mapped_column(String(50), default="requirements")
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    is_hard: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    specificity: Mapped[float] = mapped_column(Float, default=0.5)
    parser_version: Mapped[str] = mapped_column(String(80), index=True)
    requirement_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job] = relationship(back_populates="requirements")
    matches: Mapped[list[RequirementMatch]] = relationship(back_populates="requirement")


class JobScore(Base):
    __tablename__ = "job_scores"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    semantic_score: Mapped[float] = mapped_column(Float)
    skill_score: Mapped[float] = mapped_column(Float)
    education_score: Mapped[float] = mapped_column(Float)
    experience_score: Mapped[float] = mapped_column(Float)
    location_score: Mapped[float] = mapped_column(Float)
    preference_score: Mapped[float] = mapped_column(Float)
    llm_score: Mapped[float] = mapped_column(Float)
    final_score: Mapped[float] = mapped_column(Float)
    rules_passed: Mapped[bool] = mapped_column(Boolean, default=True)
    rule_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    strengths: Mapped[list[str]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    risks: Mapped[list[str]] = mapped_column(JSON, default=list)
    resume_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    recommendation: Mapped[str] = mapped_column(String(30))
    reasoning_summary: Mapped[str] = mapped_column(Text, default="")
    score_version: Mapped[str] = mapped_column(String(50))
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    judge_source: Mapped[str] = mapped_column(String(30), default="llm")
    weights: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    direction_score: Mapped[float] = mapped_column(Float, default=0.0)
    score_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    score_status: Mapped[str] = mapped_column(String(30), default="SUFFICIENT", index=True)
    confidence_factors: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    hard_constraint_ledger: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    hard_constraint_passed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job] = relationship(back_populates="scores")
    resume: Mapped[Resume] = relationship(back_populates="scores")
    requirement_matches: Mapped[list[RequirementMatch]] = relationship(
        back_populates="job_score", cascade="all, delete-orphan"
    )


class RequirementMatch(Base):
    """Explainable comparison between one JD requirement and resume evidence."""

    __tablename__ = "requirement_matches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_score_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_scores.id", ondelete="CASCADE"), index=True
    )
    job_requirement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_requirements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requirement_type: Mapped[str] = mapped_column(String(40), index=True)
    requirement_value: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), index=True)
    score: Mapped[float] = mapped_column(Float)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    match_method: Mapped[str] = mapped_column(String(50), default="deterministic")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    deduction: Mapped[float] = mapped_column(Float, default=0.0)
    hard_constraint: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job_score: Mapped[JobScore] = relationship(back_populates="requirement_matches")
    requirement: Mapped[JobRequirement | None] = relationship(back_populates="matches")


class RankingRun(Base):
    __tablename__ = "ranking_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    resume_id: Mapped[UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True, index=True
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=1800)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    processed_candidates: Mapped[int] = mapped_column(Integer, default=0)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0)
    request_payload: Mapped[dict[str, Any]] = mapped_column("request", JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column("result", JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resume: Mapped[Resume] = relationship(back_populates="ranking_runs")
    campaign: Mapped[Campaign | None] = relationship(back_populates="ranking_runs")


class MarketInsightReport(Base):
    __tablename__ = "market_insight_reports"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(String(500), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="fast")
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[str] = mapped_column(String(20), default="insufficient")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column("request", JSON, default=dict)
    report_payload: Mapped[dict[str, Any]] = mapped_column("report", JSON, default=dict)
    source_job_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    llm_source: Mapped[str] = mapped_column(String(30), default="deterministic")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="market_insight_reports")


class JobVersion(Base):
    __tablename__ = "job_versions"
    __table_args__ = (
        UniqueConstraint("job_id", "version_number", name="uq_job_versions_job_version"),
        UniqueConstraint("job_id", "content_hash", name="uq_job_versions_job_content_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    raw_title: Mapped[str] = mapped_column(String(300), default="")
    raw_description: Mapped[str] = mapped_column(Text, default="")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(128))
    source_platform: Mapped[str] = mapped_column(String(100), default="")
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parser_version: Mapped[str] = mapped_column(String(80), default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job] = relationship(back_populates="versions")
    knowledge_document: Mapped[JobKnowledgeDocument | None] = relationship(
        back_populates="job_version", uselist=False, cascade="all, delete-orphan"
    )


class JobKnowledgeDocument(Base):
    __tablename__ = "job_knowledge_documents"
    __table_args__ = (
        UniqueConstraint("job_version_id", name="uq_job_knowledge_documents_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    job_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_versions.id", ondelete="CASCADE"), index=True
    )
    role_family: Mapped[str] = mapped_column(String(200), default="")
    normalized_title: Mapped[str] = mapped_column(String(300), default="")
    normalized_city: Mapped[str] = mapped_column(String(300), default="")
    normalized_education: Mapped[str] = mapped_column(String(500), default="")
    normalized_experience: Mapped[str] = mapped_column(String(500), default="")
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_unit: Mapped[str] = mapped_column(String(40), default="")
    employment_type: Mapped[str] = mapped_column(String(100), default="")
    current_embedding_signature: Mapped[str] = mapped_column(String(300), default="")
    knowledge_version: Mapped[str] = mapped_column(String(80), default="JOB_KNOWLEDGE_V1")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    job: Mapped[Job] = relationship(back_populates="knowledge_documents")
    job_version: Mapped[JobVersion] = relationship(back_populates="knowledge_document")
    chunks: Mapped[list[JobKnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class JobKnowledgeChunk(Base):
    __tablename__ = "job_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "section_type",
            "content_hash",
            name="uq_job_knowledge_chunks_document_section_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    section_type: Mapped[str] = mapped_column(String(60), index=True)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(1024), nullable=True)
    embedding_provider: Mapped[str] = mapped_column(String(80), default="")
    embedding_model: Mapped[str] = mapped_column(String(200), default="")
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=1024)
    embedding_signature: Mapped[str] = mapped_column(String(300), default="", index=True)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    document: Mapped[JobKnowledgeDocument] = relationship(back_populates="chunks")
    job: Mapped[Job] = relationship(back_populates="knowledge_chunks")


class SkillTaxonomy(Base):
    __tablename__ = "skill_taxonomy"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(100), default="other", index=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("skill_taxonomy.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    parent: Mapped[SkillTaxonomy | None] = relationship(
        remote_side="SkillTaxonomy.id", back_populates="children"
    )
    children: Mapped[list[SkillTaxonomy]] = relationship(back_populates="parent")
    aliases: Mapped[list[SkillAlias]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )
    job_facts: Mapped[list[JobSkillFact]] = relationship(back_populates="skill")


class SkillAlias(Base):
    __tablename__ = "skill_aliases"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_taxonomy.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(String(160))
    normalized_alias: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    skill: Mapped[SkillTaxonomy] = relationship(back_populates="aliases")


class JobSkillFact(Base):
    __tablename__ = "job_skill_facts"
    __table_args__ = (UniqueConstraint("job_id", "skill_id", name="uq_job_skill_facts_job_skill"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_taxonomy.id", ondelete="CASCADE"), index=True
    )
    requirement_type: Mapped[str] = mapped_column(String(30), index=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    parser_version: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job] = relationship(back_populates="skill_facts")
    skill: Mapped[SkillTaxonomy] = relationship(back_populates="job_facts")


class KnowledgeIndexRun(Base):
    __tablename__ = "knowledge_index_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    mode: Mapped[str] = mapped_column(String(30), default="incremental", index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    stage: Mapped[str] = mapped_column(String(50), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    processed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    succeeded_jobs: Mapped[int] = mapped_column(Integer, default=0)
    skipped_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    current_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column("request", JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column("result", JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    current_job: Mapped[Job | None] = relationship(foreign_keys=[current_job_id])
    items: Mapped[list[KnowledgeIndexRunItem]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class KnowledgeIndexRunItem(Base):
    __tablename__ = "knowledge_index_run_items"
    __table_args__ = (
        UniqueConstraint("run_id", "job_id", name="uq_knowledge_index_items_run_job"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_index_runs.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    reused_embedding_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[KnowledgeIndexRun] = relationship(back_populates="items")
    job: Mapped[Job] = relationship()


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    status_before_pause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    query: Mapped[str] = mapped_column(Text, default="")
    min_score: Mapped[float] = mapped_column(Float, default=70.0)
    max_jobs: Mapped[int] = mapped_column(Integer, default=20)
    scoring_mode: Mapped[str] = mapped_column(String(20), default="fast")
    target_cities: Mapped[list[str]] = mapped_column(JSON, default=list)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="campaigns")
    resume: Mapped[Resume | None] = relationship(back_populates="campaigns")
    campaign_jobs: Mapped[list[CampaignJob]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    applications: Mapped[list[Application]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    ranking_runs: Mapped[list[RankingRun]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(back_populates="campaign")
    browser_tasks: Mapped[list[BrowserTask]] = relationship(back_populates="campaign")


class CampaignJob(Base):
    __tablename__ = "campaign_jobs"
    __table_args__ = (
        UniqueConstraint("campaign_id", "job_id", name="uq_campaign_jobs_campaign_job"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(40), default="WAITING_APPROVAL", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    campaign: Mapped[Campaign] = relationship(back_populates="campaign_jobs")
    job: Mapped[Job] = relationship(back_populates="campaign_jobs")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("campaign_id", "job_id", name="uq_applications_campaign_job"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="DISCOVERED", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    application_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="applications")
    campaign: Mapped[Campaign] = relationship(back_populates="applications")
    job: Mapped[Job] = relationship(back_populates="applications")
    resume: Mapped[Resume] = relationship(back_populates="applications")
    browser_tasks: Mapped[list[BrowserTask]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class BrowserTask(Base):
    __tablename__ = "browser_tasks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[str] = mapped_column(String(100), default="mock", index=True)
    task_type: Mapped[str] = mapped_column(String(80), default="submit_application")
    scenario: Mapped[str] = mapped_column(String(40), default="SUCCESS")
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_action: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="browser_tasks")
    application: Mapped[Application] = relationship(back_populates="browser_tasks")
    campaign: Mapped[Campaign | None] = relationship(back_populates="browser_tasks")
    events: Mapped[list[BrowserTaskEvent]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class BrowserTaskEvent(Base):
    __tablename__ = "browser_task_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey("browser_tasks.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    action_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    task: Mapped[BrowserTask] = relationship(back_populates="events")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent_type: Mapped[str] = mapped_column(String(100), default="job_search_orchestrator")
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    status_before_pause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    run_input: Mapped[dict[str, Any]] = mapped_column("input", JSON, default=dict)
    run_output: Mapped[dict[str, Any]] = mapped_column("output", JSON, default=dict)
    agent_state: Mapped[dict[str, Any]] = mapped_column("state", JSON, default=dict)
    memory: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    max_steps: Mapped[int] = mapped_column(Integer, default=12)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="agent_runs")
    campaign: Mapped[Campaign | None] = relationship(back_populates="agent_runs")
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[list[AgentEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_agent_steps_sequence"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(50))
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    step_input: Mapped[dict[str, Any]] = mapped_column("input", JSON, default=dict)
    step_output: Mapped[dict[str, Any]] = mapped_column("output", JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped[AgentRun] = relationship(back_populates="events")


class AgentToolInvocation(Base):
    """Durable, provider-neutral record of one attempted tool execution."""

    __tablename__ = "agent_tool_invocations"
    __table_args__ = (
        UniqueConstraint("run_id", "call_id", name="uq_agent_tool_invocations_run_call"),
        UniqueConstraint(
            "run_id", "idempotency_key", "attempt", name="uq_agent_tool_invocations_idempotency"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    call_id: Mapped[str] = mapped_column(String(300))
    idempotency_key: Mapped[str] = mapped_column(String(300), index=True)
    parent_call_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(200), index=True)
    source: Mapped[str] = mapped_column(String(30), default="local", index=True)
    server_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CareerAdvisorSession(Base):
    __tablename__ = "career_advisor_sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="新职业咨询")
    agent_type: Mapped[str] = mapped_column(String(50), default="career_advisor")
    context_filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="career_advisor_sessions")
    messages: Mapped[list[CareerAdvisorMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    job_links: Mapped[list[CareerAdvisorSessionJob]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class CareerAdvisorSessionJob(Base):
    """A durable reference from one advisor conversation to a persisted job."""

    __tablename__ = "career_advisor_session_jobs"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "job_id",
            name="uq_career_advisor_session_jobs_session_job",
        ),
        Index(
            "ix_career_advisor_session_jobs_session_last_linked",
            "session_id",
            "last_linked_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("career_advisor_sessions.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("career_advisor_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(40), default="automated_collection", index=True
    )
    context_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    first_linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    session: Mapped[CareerAdvisorSession] = relationship(back_populates="job_links")
    job: Mapped[Job] = relationship(back_populates="career_advisor_links")


class CareerAdvisorMessage(Base):
    __tablename__ = "career_advisor_messages"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("career_advisor_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED", index=True)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    model_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tool_trace: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answer_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    session: Mapped[CareerAdvisorSession] = relationship(back_populates="messages")
    citations: Mapped[list[CareerAdvisorCitation]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class CareerAdvisorCitation(Base):
    __tablename__ = "career_advisor_citations"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "citation_index",
            name="uq_career_advisor_citations_message_index",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("career_advisor_messages.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_knowledge_chunks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    citation_index: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[str] = mapped_column(Text, default="")
    citation_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    message: Mapped[CareerAdvisorMessage] = relationship(back_populates="citations")


class AgentMemorySetting(Base):
    __tablename__ = "agent_memory_settings"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_save_non_sensitive: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int] = mapped_column(Integer, default=180)
    allowed_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    allow_session_summaries: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_unconfirmed_context: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_token_budget: Mapped[int] = mapped_column(Integer, default=700)
    extraction_confidence_threshold: Mapped[float] = mapped_column(Float, default=0.75)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="memory_settings")


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_agent_memories_user_hash"),
        Index("ix_agent_memories_user_status", "user_id", "status"),
        Index("ix_agent_memories_user_memory_key", "user_id", "memory_key"),
        Index("ix_agent_memories_user_type", "user_id", "memory_type"),
        Index("ix_agent_memories_user_valid_until", "user_id", "valid_until"),
        Index("ix_agent_memories_embedding_signature", "embedding_signature"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    memory_type: Mapped[str] = mapped_column(String(50), index=True)
    memory_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    structured_value: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=dict
    )
    scope: Mapped[str | None] = mapped_column(String(120), nullable=True)
    memory_class: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    stability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_memories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    source_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("career_advisor_sessions.id", ondelete="SET NULL"), nullable=True
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("career_advisor_messages.id", ondelete="SET NULL"), nullable=True
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sensitivity: Mapped[str] = mapped_column(String(30), default="NORMAL", index=True)
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType(1024), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_signature: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="agent_memories")


class MemoryCandidate(Base):
    __tablename__ = "memory_candidates"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_memory_candidates_user_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    memory_type: Mapped[str] = mapped_column(String(50), index=True)
    memory_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    structured_value: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=dict
    )
    scope: Mapped[str | None] = mapped_column(String(120), nullable=True)
    memory_class: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stability: Mapped[str | None] = mapped_column(String(20), nullable=True)
    importance: Mapped[float | None] = mapped_column(Float, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    normalized_content: Mapped[str] = mapped_column(Text)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    extraction_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    conflict_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("career_advisor_sessions.id", ondelete="SET NULL"), nullable=True
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("career_advisor_messages.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    sensitivity: Mapped[str] = mapped_column(String(30), default="NORMAL")
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="memory_candidates")


class MemoryEmbeddingRun(Base):
    """Durable lifecycle record for long-term-memory embedding backfills."""

    __tablename__ = "memory_embedding_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(30), default="incremental", index=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    current_memory_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_memories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column("request", JSON, default=dict)
    result_payload: Mapped[dict[str, Any]] = mapped_column("result", JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MCPConnection(Base):
    __tablename__ = "mcp_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "namespace", name="uq_mcp_connections_user_namespace"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    namespace: Mapped[str] = mapped_column(String(80))
    transport: Mapped[str] = mapped_column(String(30))
    endpoint: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    arguments: Mapped[list[str]] = mapped_column(JSON, default=list)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="DISABLED", index=True)
    permission_scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    blocked_tools: Mapped[list[str]] = mapped_column(JSON, default=list)
    connect_timeout: Mapped[float] = mapped_column(Float, default=10.0)
    tool_timeout: Mapped[float] = mapped_column(Float, default=30.0)
    last_health_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    user: Mapped[User] = relationship(back_populates="mcp_connections")
    discovered_tools: Mapped[list[MCPDiscoveredTool]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )


class MCPDiscoveredTool(Base):
    __tablename__ = "mcp_discovered_tools"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "remote_name", name="uq_mcp_tools_connection_remote_name"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_connections.id", ondelete="CASCADE"), index=True
    )
    remote_name: Mapped[str] = mapped_column(String(200))
    canonical_name: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    schema_hash: Mapped[str] = mapped_column(String(64), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    connection: Mapped[MCPConnection] = relationship(back_populates="discovered_tools")


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        UniqueConstraint("suite", "version", name="uq_evaluation_datasets_suite_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    suite: Mapped[str] = mapped_column(String(50), index=True)
    version: Mapped[str] = mapped_column(String(80))
    label_status: Mapped[str] = mapped_column(String(50), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list[EvaluationRun]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress_current: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    dataset: Mapped[EvaluationDataset] = relationship(back_populates="runs")
