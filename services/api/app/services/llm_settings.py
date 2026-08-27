from __future__ import annotations

import base64
import hashlib
from time import perf_counter
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.llm.provider import (
    DEFAULT_PROVIDER_BASE_URLS,
    DEFAULT_PROVIDER_MODELS,
    AnthropicProvider,
    LLMProvider,
    LLMProviderError,
    MockLLMProvider,
    OpenAIProvider,
)
from app.models.entities import LLMProviderCredential, User
from app.schemas.llm import (
    ActiveProviderName,
    LLMConnectionTestRead,
    LLMProviderRead,
    LLMSettingsRead,
    ProviderName,
)


class LLMProviderNotConfiguredError(ValueError):
    """Raised when a requested remote provider has no saved API key."""


class LLMProviderConfigurationError(ValueError):
    """Raised when a saved provider configuration is invalid."""


class LLMSettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self._fernet = Fernet(self._derive_fernet_key(self.settings.llm_encryption_key))

    async def read(self) -> LLMSettingsRead:
        user = await self._find_default_user()
        credentials: list[LLMProviderCredential] = []
        if user is not None:
            credentials = list(
                (
                    await self.session.scalars(
                        select(LLMProviderCredential)
                        .where(LLMProviderCredential.user_id == user.id)
                        .order_by(LLMProviderCredential.provider)
                    )
                ).all()
            )

        active_provider = self._active_provider(credentials, user)
        return LLMSettingsRead(
            active_provider=active_provider,
            providers=[LLMProviderRead.model_validate(item) for item in credentials],
        )

    async def upsert(
        self,
        provider: ProviderName,
        *,
        api_key: str,
        model: str,
        base_url: str,
    ) -> LLMSettingsRead:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise LLMProviderConfigurationError("API key cannot be empty")

        user = await self._get_or_create_default_user()
        credential = await self.session.scalar(
            select(LLMProviderCredential).where(
                LLMProviderCredential.user_id == user.id,
                LLMProviderCredential.provider == provider,
            )
        )
        if credential is None:
            credential = LLMProviderCredential(user_id=user.id, provider=provider)
            self.session.add(credential)

        credential.model = model.strip() or DEFAULT_PROVIDER_MODELS[provider]
        credential.base_url = base_url.strip() or DEFAULT_PROVIDER_BASE_URLS[provider]
        credential.api_key_encrypted = self._fernet.encrypt(normalized_key.encode()).decode()
        credential.api_key_hint = mask_api_key(normalized_key)
        credential.is_active = True
        user.llm_active_provider = provider
        await self.session.execute(
            update(LLMProviderCredential)
            .where(
                LLMProviderCredential.user_id == user.id,
                LLMProviderCredential.provider != provider,
            )
            .values(is_active=False)
        )
        await self.session.commit()
        return await self.read()

    async def test_connection(
        self,
        provider: ProviderName,
        *,
        api_key: str,
        model: str,
        base_url: str,
    ) -> LLMConnectionTestRead:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise LLMProviderConfigurationError("API key cannot be empty")
        resolved_model = model.strip() or DEFAULT_PROVIDER_MODELS[provider]
        remote_provider = self._build_remote_provider_from_values(
            provider, normalized_key, resolved_model, base_url.strip()
        )
        return await self._run_connection_test(provider, resolved_model, remote_provider)

    async def test_saved_connection(self, provider: ProviderName) -> LLMConnectionTestRead:
        user = await self._find_default_user()
        if user is None:
            raise LLMProviderNotConfiguredError(f"{provider} API key is not configured")
        credential = await self.session.scalar(
            select(LLMProviderCredential).where(
                LLMProviderCredential.user_id == user.id,
                LLMProviderCredential.provider == provider,
            )
        )
        if credential is None:
            raise LLMProviderNotConfiguredError(f"{provider} API key is not configured")
        resolved_model = credential.model or DEFAULT_PROVIDER_MODELS[provider]
        return await self._run_connection_test(
            provider, resolved_model, self._build_remote_provider(credential)
        )

    async def set_active(self, provider: ActiveProviderName) -> LLMSettingsRead:
        user = await self._find_default_user()
        if provider == "mock":
            user = user or await self._get_or_create_default_user()
            await self.session.execute(
                update(LLMProviderCredential)
                .where(LLMProviderCredential.user_id == user.id)
                .values(is_active=False)
            )
            user.llm_active_provider = "mock"
            await self.session.commit()
            return await self.read()

        if user is None:
            raise LLMProviderNotConfiguredError(f"{provider} API key is not configured")
        credential = await self.session.scalar(
            select(LLMProviderCredential).where(
                LLMProviderCredential.user_id == user.id,
                LLMProviderCredential.provider == provider,
            )
        )
        if credential is None:
            raise LLMProviderNotConfiguredError(f"{provider} API key is not configured")

        await self.session.execute(
            update(LLMProviderCredential)
            .where(LLMProviderCredential.user_id == user.id)
            .values(is_active=False)
        )
        credential.is_active = True
        user.llm_active_provider = provider
        await self.session.commit()
        return await self.read()

    async def delete(self, provider: ProviderName) -> LLMSettingsRead:
        user = await self._find_default_user()
        if user is None:
            raise LLMProviderNotConfiguredError(f"{provider} API key is not configured")
        credential = await self.session.scalar(
            select(LLMProviderCredential).where(
                LLMProviderCredential.user_id == user.id,
                LLMProviderCredential.provider == provider,
            )
        )
        if credential is None:
            raise LLMProviderNotConfiguredError(f"{provider} API key is not configured")
        was_active = credential.is_active
        await self.session.delete(credential)
        if was_active:
            user.llm_active_provider = "mock"
        await self.session.commit()
        return await self.read()

    async def get_runtime_provider(self) -> LLMProvider:
        user = await self._find_default_user()
        if user is not None:
            if user.llm_active_provider == "mock":
                return MockLLMProvider(dimensions=self.settings.embedding_dimensions)
            credential = await self.session.scalar(
                select(LLMProviderCredential).where(
                    LLMProviderCredential.user_id == user.id,
                    LLMProviderCredential.is_active.is_(True),
                )
            )
            if credential is not None:
                return self._build_remote_provider(credential)

        # Keep the existing environment-based setup working for deployments
        # that configured a key before the settings screen existed.
        env_provider = self.settings.llm_provider.strip().lower()
        env_key = self.settings.llm_api_key.strip()
        if env_provider in ("openai", "anthropic") and env_key:
            return self._build_remote_provider_from_values(
                env_provider, env_key, self.settings.llm_model, self.settings.llm_base_url
            )
        return MockLLMProvider(dimensions=self.settings.embedding_dimensions)

    async def get_runtime_embedding_provider(self) -> LLMProvider:
        """Resolve the vector provider independently from the judge provider."""

        provider = self.settings.embedding_provider.strip().lower()
        if provider in {"", "auto"}:
            return await self.get_runtime_provider()
        if provider == "mock":
            return MockLLMProvider(dimensions=self.settings.embedding_dimensions)
        if provider not in {"openai", "anthropic"}:
            raise LLMProviderConfigurationError(
                f"Unsupported embedding provider: {self.settings.embedding_provider}"
            )

        api_key = self.settings.embedding_api_key.strip()
        if api_key:
            return self._build_remote_provider_from_values(
                provider,
                api_key,
                self.settings.llm_model,
                self.settings.embedding_base_url,
            )

        user = await self._find_default_user()
        if user is not None:
            credential = await self.session.scalar(
                select(LLMProviderCredential).where(
                    LLMProviderCredential.user_id == user.id,
                    LLMProviderCredential.provider == provider,
                )
            )
            if credential is not None:
                return self._build_remote_provider(credential)
        raise LLMProviderNotConfiguredError(
            f"{provider} embedding API key is not configured"
        )

    async def _run_connection_test(
        self, provider: ProviderName, model: str, remote_provider: LLMProvider
    ) -> LLMConnectionTestRead:
        started = perf_counter()
        await remote_provider.generate("Reply with exactly: OK", model=model)
        return LLMConnectionTestRead(
            provider=provider,
            model=model,
            latency_ms=round((perf_counter() - started) * 1000, 1),
            message="连接成功，未修改已保存配置",
        )

    def _build_remote_provider(self, credential: LLMProviderCredential) -> LLMProvider:
        try:
            api_key = self._fernet.decrypt(credential.api_key_encrypted.encode()).decode()
        except (InvalidToken, ValueError) as exc:
            raise LLMProviderError(
                "LLM credential cannot be decrypted; check LLM_ENCRYPTION_KEY"
            ) from exc
        return self._build_remote_provider_from_values(
            credential.provider, api_key, credential.model, credential.base_url
        )

    def _build_remote_provider_from_values(
        self, provider: str, api_key: str, model: str, base_url: str
    ) -> LLMProvider:
        kwargs = {
            "api_key": api_key,
            "model": model or DEFAULT_PROVIDER_MODELS[provider],
            "base_url": base_url or DEFAULT_PROVIDER_BASE_URLS[provider],
            "dimensions": self.settings.embedding_dimensions,
            "embedding_model": self.settings.embedding_model,
            "structured_max_tokens": self.settings.llm_structured_max_tokens,
            "structured_retry_max_tokens": self.settings.llm_structured_retry_max_tokens,
        }
        if provider == "openai":
            return OpenAIProvider(**kwargs)
        if provider == "anthropic":
            return AnthropicProvider(**kwargs)
        raise LLMProviderConfigurationError(f"Unsupported LLM provider: {provider}")

    async def _find_default_user(self) -> User | None:
        return await self.session.scalar(
            select(User).where(User.email == self.settings.default_user_email)
        )

    async def _get_or_create_default_user(self) -> User:
        user = await self._find_default_user()
        if user is not None:
            return user
        user = User(email=self.settings.default_user_email, name=self.settings.default_user_name)
        self.session.add(user)
        await self.session.flush()
        return user

    def _active_provider(
        self, credentials: list[LLMProviderCredential], user: User | None
    ) -> Literal["mock", "openai", "anthropic"]:
        if user and user.llm_active_provider in ("mock", "openai", "anthropic"):
            return user.llm_active_provider  # type: ignore[return-value]
        for credential in credentials:
            if credential.is_active and credential.provider in ("openai", "anthropic"):
                return credential.provider  # type: ignore[return-value]
        env_provider = self.settings.llm_provider.strip().lower()
        if env_provider in ("openai", "anthropic") and self.settings.llm_api_key.strip():
            return env_provider  # type: ignore[return-value]
        return "mock"

    @staticmethod
    def _derive_fernet_key(secret: str) -> bytes:
        try:
            decoded = base64.urlsafe_b64decode(secret.encode())
            if len(decoded) == 32:
                return secret.encode()
        except (ValueError, base64.binascii.Error):
            pass
        return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def mask_api_key(api_key: str) -> str:
    suffix = api_key[-4:] if len(api_key) >= 4 else api_key
    return f"••••{suffix}"
