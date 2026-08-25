from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.llm.provider import LLMProvider, MockLLMProvider
from app.services.agent_runtime import AgentRuntime
from app.services.browser_tasks import BrowserTaskService
from app.services.campaigns import CampaignService
from app.services.jobs import JobService
from app.services.matching import MatchingService
from app.services.ranking import RankingService
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


def get_matching_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> MatchingService:
    return MatchingService(session, provider)


def get_ranking_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> RankingService:
    return RankingService(session, provider)


def get_campaign_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> CampaignService:
    return CampaignService(session, provider)


def get_agent_runtime(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> AgentRuntime:
    return AgentRuntime(session, provider)


def get_browser_task_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> BrowserTaskService:
    return BrowserTaskService(session, provider)
