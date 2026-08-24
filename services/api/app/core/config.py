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
    embedding_dimensions: int = Field(default=384, validation_alias="EMBEDDING_DIMENSIONS")
    embedding_model: str = Field(default="mock-hash-384", validation_alias="EMBEDDING_MODEL")
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
    top_k_rerank: int = Field(default=30, validation_alias="TOP_K_RERANK")
    top_k_llm: int = Field(default=15, validation_alias="TOP_K_LLM")
    final_ranking_top_k: int = Field(default=10, validation_alias="FINAL_RANKING_TOP_K")
    ranking_version: str = Field(default="RANKING_V1", validation_alias="RANKING_VERSION")

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
