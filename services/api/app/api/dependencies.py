from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.llm.provider import LLMProvider, MockLLMProvider
from app.services.jobs import JobService
from app.services.resumes import ResumeService


def get_job_service(session: AsyncSession = Depends(get_db)) -> JobService:
    return JobService(session)


def get_llm_provider() -> LLMProvider:
    return MockLLMProvider(dimensions=get_settings().embedding_dimensions)


def get_resume_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> ResumeService:
    return ResumeService(session, embedding_provider=provider)
