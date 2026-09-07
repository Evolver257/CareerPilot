from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CareerPilot API"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://4careerpilot:careerpilot@localhost:5432/careerpilot"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = Field(default="http://localhost:3000", validation_alias="CORS_ORIGINS")
    max_upload_size_bytes: int = Field(
        default=10 * 1024 * 1024, validation_alias="MAX_UPLOAD_SIZE_BYTES"
    )
    embedding_dimensions: int = Field(default=1024, validation_alias="EMBEDDING_DIMENSIONS")
    embedding_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B", validation_alias="EMBEDDING_MODEL"
    )
    embedding_provider: str = Field(default="auto", validation_alias="EMBEDDING_PROVIDER")
    embedding_api_key: str = Field(default="", validation_alias="EMBEDDING_API_KEY")
    embedding_base_url: str = Field(default="", validation_alias="EMBEDDING_BASE_URL")
    semantic_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B",
        validation_alias="SEMANTIC_MODEL",
    )
    semantic_cache_dir: str | None = Field(default=None, validation_alias="SEMANTIC_CACHE_DIR")
    rag_reranker: str = Field(default="local", validation_alias="RAG_RERANKER")
    semantic_reranker_model: str = Field(
        default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        validation_alias="SEMANTIC_RERANKER_MODEL",
    )
    independent_worker: bool = Field(default=True, validation_alias="INDEPENDENT_WORKER")
    llm_provider: str = Field(default="mock", validation_alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_model: str = Field(default="", validation_alias="LLM_MODEL")
    llm_base_url: str = Field(default="", validation_alias="LLM_BASE_URL")
    llm_structured_max_tokens: int = Field(
        default=8192, gt=0, validation_alias="LLM_STRUCTURED_MAX_TOKENS"
    )
    llm_structured_retry_max_tokens: int = Field(
        default=12288, gt=0, validation_alias="LLM_STRUCTURED_RETRY_MAX_TOKENS"
    )
    llm_encryption_key: str = Field(
        default="development-only-change-me",
        validation_alias="LLM_ENCRYPTION_KEY",
    )
    default_user_email: str = Field(
        default="demo@careerpilot.local", validation_alias="DEFAULT_USER_EMAIL"
    )
    default_user_name: str = Field(default="Demo User", validation_alias="DEFAULT_USER_NAME")
    matching_semantic_weight: float = Field(
        default=0.25, validation_alias="MATCHING_SEMANTIC_WEIGHT"
    )
    matching_skill_weight: float = Field(default=0.25, validation_alias="MATCHING_SKILL_WEIGHT")
    matching_education_weight: float = Field(
        default=0.15, validation_alias="MATCHING_EDUCATION_WEIGHT"
    )
    matching_experience_weight: float = Field(
        default=0.10, validation_alias="MATCHING_EXPERIENCE_WEIGHT"
    )
    matching_location_weight: float = Field(
        default=0.10, validation_alias="MATCHING_LOCATION_WEIGHT"
    )
    matching_preference_weight: float = Field(
        default=0.10, validation_alias="MATCHING_PREFERENCE_WEIGHT"
    )
    matching_llm_weight: float = Field(default=0.05, validation_alias="MATCHING_LLM_WEIGHT")
    matching_retrieval_top_k: int = Field(default=8, validation_alias="MATCHING_RETRIEVAL_TOP_K")
    matching_rerank_top_k: int = Field(default=4, validation_alias="MATCHING_RERANK_TOP_K")
    matching_score_version: str = Field(
        default="MATCHING_V1", validation_alias="MATCHING_SCORE_VERSION"
    )
    ranking_candidate_limit: int = Field(default=300, validation_alias="RANKING_CANDIDATE_LIMIT")
    top_k_embedding: int = Field(default=100, validation_alias="TOP_K_EMBEDDING")
    top_k_rerank: int = Field(default=10, validation_alias="TOP_K_RERANK")
    top_k_llm: int = Field(default=10, validation_alias="TOP_K_LLM")
    final_ranking_top_k: int = Field(default=10, validation_alias="FINAL_RANKING_TOP_K")
    ranking_version: str = Field(default="RANKING_V1", validation_alias="RANKING_VERSION")
    ranking_timeout_seconds: int = Field(
        default=1800, validation_alias="RANKING_TIMEOUT_SECONDS", ge=30, le=7200
    )
    auto_delivery_max_job_age_days: int = Field(
        default=3,
        ge=1,
        le=30,
        validation_alias="AUTO_DELIVERY_MAX_JOB_AGE_DAYS",
    )
    rag_agentic_enabled: bool = Field(default=True, validation_alias="RAG_AGENTIC_ENABLED")
    rag_keyword_top_k: int = Field(default=30, ge=5, le=300, validation_alias="RAG_KEYWORD_TOP_K")
    rag_vector_top_k: int = Field(default=30, ge=5, le=300, validation_alias="RAG_VECTOR_TOP_K")
    rag_fusion_top_k: int = Field(default=40, ge=5, le=200, validation_alias="RAG_FUSION_TOP_K")
    rag_rerank_top_k: int = Field(default=12, ge=3, le=30, validation_alias="RAG_RERANK_TOP_K")
    rag_rrf_k: float = Field(default=60.0, ge=1.0, le=500.0, validation_alias="RAG_RRF_K")
    rag_sparse_weight: float = Field(
        default=0.55, ge=0.0, le=1.0, validation_alias="RAG_SPARSE_WEIGHT"
    )
    rag_dense_weight: float = Field(
        default=0.45, ge=0.0, le=1.0, validation_alias="RAG_DENSE_WEIGHT"
    )
    rag_evidence_max_items: int = Field(
        default=12, ge=3, le=30, validation_alias="RAG_EVIDENCE_MAX_ITEMS"
    )
    rag_max_iterations: int = Field(default=2, ge=1, le=3, validation_alias="RAG_MAX_ITERATIONS")
    rag_max_queries: int = Field(default=6, ge=1, le=8, validation_alias="RAG_MAX_QUERIES")
    rag_llm_planner_enabled: bool = Field(
        default=True, validation_alias="RAG_LLM_PLANNER_ENABLED"
    )
    rag_planner_shadow_mode: bool = Field(
        default=False, validation_alias="RAG_PLANNER_SHADOW_MODE"
    )
    rag_reflection_enabled: bool = Field(
        default=True, validation_alias="RAG_REFLECTION_ENABLED"
    )
    rag_answer_reflection_enabled: bool = Field(
        default=True, validation_alias="RAG_ANSWER_REFLECTION_ENABLED"
    )
    rag_max_reflection_iterations: int = Field(
        default=2, ge=0, le=3, validation_alias="RAG_MAX_REFLECTION_ITERATIONS"
    )
    rag_max_answer_repairs: int = Field(
        default=1, ge=0, le=2, validation_alias="RAG_MAX_ANSWER_REPAIRS"
    )
    rag_max_tool_calls: int = Field(default=8, ge=1, le=20, validation_alias="RAG_MAX_TOOL_CALLS")
    agent_tool_timeout_seconds: float = Field(
        default=30,
        ge=0.1,
        le=300,
        validation_alias="AGENT_TOOL_TIMEOUT_SECONDS",
    )
    mcp_discovery_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        validation_alias="MCP_DISCOVERY_TTL_SECONDS",
    )
    rag_min_evidence_gain: float = Field(
        default=0.1, ge=0, le=1, validation_alias="RAG_MIN_EVIDENCE_GAIN"
    )
    rag_planner_max_tokens: int = Field(
        default=600, ge=200, le=2000, validation_alias="RAG_PLANNER_MAX_TOKENS"
    )
    rag_reflection_max_tokens: int = Field(
        default=500, ge=200, le=1600, validation_alias="RAG_REFLECTION_MAX_TOKENS"
    )
    rag_planner_confidence_threshold: float = Field(
        default=0.55, ge=0, le=1, validation_alias="RAG_PLANNER_CONFIDENCE_THRESHOLD"
    )
    rag_workflow_timeout_seconds: int = Field(
        default=60, ge=5, le=300, validation_alias="RAG_WORKFLOW_TIMEOUT_SECONDS"
    )
    rag_context_max_tokens: int = Field(
        default=8000, ge=1000, le=32000, validation_alias="RAG_CONTEXT_MAX_TOKENS"
    )
    rag_context_primary_ratio: float = Field(
        default=0.60,
        ge=0.1,
        le=0.9,
        validation_alias="RAG_CONTEXT_PRIMARY_RATIO",
    )
    rag_context_supporting_ratio: float = Field(
        default=0.25,
        ge=0.05,
        le=0.8,
        validation_alias="RAG_CONTEXT_SUPPORTING_RATIO",
    )
    rag_context_background_ratio: float = Field(
        default=0.15,
        ge=0.05,
        le=0.8,
        validation_alias="RAG_CONTEXT_BACKGROUND_RATIO",
    )
    rag_evidence_min_coverage: float = Field(
        default=0.65, ge=0.2, le=1.0, validation_alias="RAG_EVIDENCE_MIN_COVERAGE"
    )
    rag_evidence_min_relevance: float = Field(
        default=0.42, ge=0.1, le=1.0, validation_alias="RAG_EVIDENCE_MIN_RELEVANCE"
    )
    rag_verification_enabled: bool = Field(
        default=True, validation_alias="RAG_VERIFICATION_ENABLED"
    )
    rag_parent_child_enabled: bool = Field(
        default=False, validation_alias="RAG_PARENT_CHILD_ENABLED"
    )
    job_possibly_expired_days: int = Field(
        default=14, ge=1, le=365, validation_alias="JOB_POSSIBLY_EXPIRED_DAYS"
    )
    job_expired_days: int = Field(default=30, ge=2, le=730, validation_alias="JOB_EXPIRED_DAYS")
    rag_min_quality_score: float = Field(
        default=0.35, ge=0.0, le=1.0, validation_alias="RAG_MIN_QUALITY_SCORE"
    )
    career_advisor_native_tools_enabled: bool = Field(
        default=True,
        validation_alias="CAREER_ADVISOR_NATIVE_TOOLS_ENABLED",
    )
    mcp_stdio_allowed_commands: str = Field(
        default="", validation_alias="MCP_STDIO_ALLOWED_COMMANDS"
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def matching_weights(self) -> dict[str, float]:
        return {
            "semantic": self.matching_semantic_weight,
            "skill": self.matching_skill_weight,
            "education": self.matching_education_weight,
            "experience": self.matching_experience_weight,
            "location": self.matching_location_weight,
            "preference": self.matching_preference_weight,
            "llm": self.matching_llm_weight,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
