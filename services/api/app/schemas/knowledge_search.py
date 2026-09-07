from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

RetrievalMode = Literal["hybrid", "full_text", "vector"]
RAGQuestionType = Literal[
    "fact_lookup",
    "concept_explanation",
    "document_lookup",
    "comparison",
    "summary",
    "multi_hop",
    "procedural",
    "time_sensitive",
    "aggregation",
]
RAGComplexity = Literal["simple", "medium", "complex"]
RAGConfidence = Literal["high", "medium", "low"]


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
    job_ids: list[UUID] = Field(default_factory=list, max_length=200)


class JobKnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)
    retrieval_mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=10, ge=1, le=200)
    full_text_top_k: int = Field(default=100, ge=1, le=300)
    vector_top_k: int = Field(default=100, ge=1, le=300)
    resume_id: UUID | None = None
    include_resume_evidence: bool = False
    force_refresh: bool = False
    rerank_mode: Literal["local", "none", "cross_encoder"] = "local"
    section_types: list[str] = Field(default_factory=list, max_length=20)


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
    document_id: UUID | None = None
    parent_id: UUID | None = None
    filename: str | None = None
    section: str | None = None
    page: int | None = None
    document_type: str = "job_description"
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
    reranker: str = "local"
    generated_at: datetime
    data_as_of: datetime | None = None
    sample_count: int
    filters: JobKnowledgeFilters
    statistics: JobKnowledgeStatistics
    citations: list[JobKnowledgeCitation] = Field(default_factory=list)
    resume_evidence: list[ResumeKnowledgeEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RAGQueryAnalysis(BaseModel):
    original_query: str
    intent: str
    question_type: RAGQuestionType
    entities: list[str] = Field(default_factory=list)
    role_entities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    time_constraints: dict[str, Any] | None = None
    document_constraints: list[str] = Field(default_factory=list)
    required_information: list[str] = Field(default_factory=list)
    complexity: RAGComplexity = "simple"


class RAGQueryRewrite(BaseModel):
    semantic_query: str
    keyword_queries: list[str] = Field(default_factory=list)
    exact_queries: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)

    @property
    def all_queries(self) -> list[str]:
        return list(
            dict.fromkeys(
                query.strip()
                for query in [
                    self.semantic_query,
                    *self.exact_queries,
                    *self.keyword_queries,
                    *self.sub_queries,
                ]
                if query.strip()
            )
        )


class RAGRetrievalQuery(BaseModel):
    """One bounded query proposed by the retrieval planner."""

    query: str = Field(default="", max_length=300)
    purpose: Literal[
        "semantic",
        "exact",
        "keyword",
        "aggregation",
        "comparison",
        "procedural",
    ] = "semantic"
    section_types: list[str] = Field(default_factory=list, max_length=20)
    channel_weights: dict[str, float] = Field(default_factory=dict)
    target_dimension: str | None = Field(default=None, max_length=100)


class RAGRepairAction(BaseModel):
    """A small, auditable retrieval repair selected by reflection."""

    action: Literal[
        "expand_query",
        "add_exact_terms",
        "change_section",
        "retrieve_statistics",
        "increase_top_k",
        "resolve_conflict",
    ] = "expand_query"
    query: str | None = Field(default=None, max_length=300)
    target_dimension: str | None = Field(default=None, max_length=100)
    section_types: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(default="", max_length=300)


class RAGPlannerPlan(BaseModel):
    """Structured output accepted from an LLM retrieval planner."""

    normalized_question: str = Field(default="", max_length=500)
    question_type: str = Field(default="fact_lookup", max_length=50)
    complexity: RAGComplexity = "simple"
    answer_dimensions: list[str] = Field(default_factory=list, max_length=20)
    queries: list[RAGRetrievalQuery] = Field(default_factory=list, max_length=8)
    hard_filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)
    soft_filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)
    preferred_channels: list[str] = Field(default_factory=list, max_length=4)
    expected_evidence: list[str] = Field(default_factory=list, max_length=20)
    keyword_top_k: int = Field(default=30, ge=5, le=300)
    vector_top_k: int = Field(default=30, ge=5, le=300)
    candidate_k: int = Field(default=40, ge=5, le=200)
    rerank_k: int = Field(default=12, ge=3, le=30)
    max_iterations: int = Field(default=2, ge=1, le=3)
    confidence: float = Field(default=0.0, ge=0, le=1)
    decision_summary: str = Field(default="", max_length=500)


class RAGRetrievalPlan(BaseModel):
    strategy: RetrievalMode = "hybrid"
    vector_search: bool = True
    keyword_search: bool = True
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    candidate_k: int = Field(default=40, ge=5, le=200)
    keyword_top_k: int = 30
    vector_top_k: int = 30
    rerank_k: int = 12
    max_iterations: int = 2
    section_types: list[str] = Field(default_factory=list)
    planned_queries: list[RAGRetrievalQuery] = Field(default_factory=list, max_length=8)
    planner_source: Literal["rules", "llm", "llm_cache", "rules_fallback"] = "rules"
    planner_confidence: float = Field(default=0, ge=0, le=1)
    plan_version: str = "rules-v1"
    preferred_channels: list[str] = Field(default_factory=list, max_length=4)
    expected_evidence: list[str] = Field(default_factory=list, max_length=20)
    hard_filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)
    soft_filters: JobKnowledgeFilters = Field(default_factory=JobKnowledgeFilters)


class RAGEvidenceSource(BaseModel):
    job_id: UUID
    chunk_id: UUID
    document_id: UUID | None = None
    parent_id: UUID | None = None
    title: str
    company: str | None = None
    filename: str | None = None
    section: str
    page: int | None = None
    source_url: str | None = None


class RAGEvidence(BaseModel):
    evidence_id: str
    topic: str
    claim: str
    evidence_text: str
    relevance_score: float = Field(ge=0, le=1)
    source_rank: int = Field(ge=1)
    sources: list[RAGEvidenceSource] = Field(default_factory=list)
    contradictory: bool = False


class RAGEvidenceEvaluation(BaseModel):
    answerable: bool
    coverage_score: float = Field(ge=0, le=1)
    max_relevance_score: float = Field(default=0, ge=0, le=1)
    missing_information: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    recommended_queries: list[str] = Field(default_factory=list)


class RAGVerification(BaseModel):
    groundedness: Literal["supported", "partially_supported", "unsupported"]
    completeness: Literal["complete", "partial", "insufficient"]
    citation_correctness: Literal["valid", "partial", "unavailable"]
    conflicts_handled: bool = True
    confidence: RAGConfidence = "low"
    unsupported_claims: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RAGEvidenceReflection(BaseModel):
    """Reflection over evidence quality, never exposed as private chain-of-thought."""

    status: Literal["sufficient", "repairable", "insufficient"] = "insufficient"
    failure_types: list[
        Literal[
            "low_recall",
            "low_precision",
            "coverage_gap",
            "conflicting_evidence",
            "stale_data",
            "missing_resume_evidence",
        ]
    ] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    repair_actions: list[RAGRepairAction] = Field(default_factory=list, max_length=8)
    confidence: float = Field(default=0, ge=0, le=1)
    decision_summary: str = Field(default="", max_length=500)


class RAGUnsupportedClaim(BaseModel):
    claim: str = Field(default="", max_length=500)
    section: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=300)


class RAGAnswerReflection(BaseModel):
    """Structured answer verification result used for bounded local repair."""

    status: Literal["valid", "repairable", "insufficient"] = "valid"
    repair_strategy: Literal["none", "remove_claim", "qualify_claim", "regenerate_section"] = "none"
    unsupported_claims: list[RAGUnsupportedClaim] = Field(default_factory=list, max_length=8)
    citation_gaps: list[str] = Field(default_factory=list, max_length=8)
    correction: str = Field(default="", max_length=1000)
    confidence: float = Field(default=0, ge=0, le=1)


class RAGTrace(BaseModel):
    trace_id: str
    retrieval_iterations: int = 0
    query_count: int = 0
    candidate_count: int = 0
    reranked_count: int = 0
    evidence_count: int = 0
    searched_queries: list[str] = Field(default_factory=list)
    latency_ms: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    degradations: list[str] = Field(default_factory=list)
    planner_source: Literal["rules", "llm", "llm_cache", "rules_fallback"] = "rules"
    planner_confidence: float = Field(default=0, ge=0, le=1)
    reflection_iterations: int = Field(default=0, ge=0, le=3)
    repair_actions: list[str] = Field(default_factory=list)
    coverage_before: float = Field(default=0, ge=0, le=1)
    coverage_after: float = Field(default=0, ge=0, le=1)
    answer_verification_status: str = "not_run"
    unsupported_claim_count: int = Field(default=0, ge=0)
    repaired_claim_count: int = Field(default=0, ge=0)
    stop_reason: str = ""
    planner_token_usage: dict[str, Any] = Field(default_factory=dict)
    reflection_token_usage: dict[str, Any] = Field(default_factory=dict)
    plan_version: str = "rules-v1"
    reflection: list[dict[str, Any]] = Field(default_factory=list)


class AgenticRAGSearchResponse(BaseModel):
    search: JobKnowledgeSearchResponse
    query_analysis: RAGQueryAnalysis
    query_rewrite: RAGQueryRewrite
    retrieval_plan: RAGRetrievalPlan
    evidence: list[RAGEvidence] = Field(default_factory=list)
    evidence_evaluation: RAGEvidenceEvaluation
    context: str = ""
    trace: RAGTrace
    knowledge_status: Literal["sufficient", "partial", "insufficient"]
    confidence: RAGConfidence
    warnings: list[str] = Field(default_factory=list)
