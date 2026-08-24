from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CareerPilot API"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://careerpilot:careerpilot@localhost:5432/careerpilot"
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

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
