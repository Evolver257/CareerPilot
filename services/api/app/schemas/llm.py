from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ProviderName = Literal["openai", "anthropic"]
ActiveProviderName = Literal["mock", "openai", "anthropic"]


class LLMProviderUpsert(BaseModel):
    api_key: str = Field(min_length=10, max_length=1000)
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=2000)


class LLMConnectionTestRequest(BaseModel):
    provider: ProviderName
    api_key: str = Field(min_length=10, max_length=1000)
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=2000)


class LLMConnectionTestRead(BaseModel):
    provider: ProviderName
    model: str
    latency_ms: float = Field(ge=0)
    message: str


class LLMProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: ProviderName
    model: str
    base_url: str
    api_key_hint: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LLMSettingsRead(BaseModel):
    active_provider: ActiveProviderName
    providers: list[LLMProviderRead]


class LLMActiveProviderUpdate(BaseModel):
    provider: ActiveProviderName
