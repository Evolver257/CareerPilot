from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_llm_settings_service
from app.llm.provider import LLMProviderError
from app.schemas.llm import (
    LLMActiveProviderUpdate,
    LLMConnectionTestRead,
    LLMConnectionTestRequest,
    LLMProviderUpsert,
    LLMSettingsRead,
    ProviderName,
)
from app.services.llm_settings import (
    LLMProviderConfigurationError,
    LLMProviderNotConfiguredError,
    LLMSettingsService,
)

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/settings", response_model=LLMSettingsRead)
async def get_llm_settings(
    service: LLMSettingsService = Depends(get_llm_settings_service),
) -> LLMSettingsRead:
    return await service.read()


@router.put("/providers/{provider}", response_model=LLMSettingsRead)
async def save_llm_provider(
    provider: ProviderName,
    payload: LLMProviderUpsert,
    service: LLMSettingsService = Depends(get_llm_settings_service),
) -> LLMSettingsRead:
    try:
        return await service.upsert(
            provider,
            api_key=payload.api_key,
            model=payload.model,
            base_url=payload.base_url,
        )
    except LLMProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/test", response_model=LLMConnectionTestRead)
async def test_llm_connection(
    payload: LLMConnectionTestRequest,
    service: LLMSettingsService = Depends(get_llm_settings_service),
) -> LLMConnectionTestRead:
    try:
        return await service.test_connection(
            payload.provider,
            api_key=payload.api_key,
            model=payload.model,
            base_url=payload.base_url,
        )
    except LLMProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/providers/{provider}/test", response_model=LLMConnectionTestRead)
async def test_saved_llm_connection(
    provider: ProviderName,
    service: LLMSettingsService = Depends(get_llm_settings_service),
) -> LLMConnectionTestRead:
    try:
        return await service.test_saved_connection(provider)
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.put("/active", response_model=LLMSettingsRead)
async def set_active_llm_provider(
    payload: LLMActiveProviderUpdate,
    service: LLMSettingsService = Depends(get_llm_settings_service),
) -> LLMSettingsRead:
    try:
        return await service.set_active(payload.provider)
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/providers/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_provider(
    provider: ProviderName,
    service: LLMSettingsService = Depends(get_llm_settings_service),
) -> None:
    try:
        await service.delete(provider)
    except LLMProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
