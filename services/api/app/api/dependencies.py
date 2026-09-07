from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.llm.provider import LLMProvider
from app.platforms.registry import RecruitmentProviderRegistry
from app.repositories.dashboard import DashboardRepository
from app.services.agent_runtime import AgentRuntime
from app.services.browser_tasks import BrowserTaskService
from app.services.campaigns import CampaignService
from app.services.career_advisor import CareerAdvisorService
from app.services.career_memory import CareerMemoryService
from app.services.dashboard import DashboardService
from app.services.evaluations import EvaluationService
from app.services.job_knowledge_rag import JobKnowledgeRAG
from app.services.jobs import JobService
from app.services.knowledge_indexing import KnowledgeIndexService
from app.services.llm_settings import LLMSettingsService
from app.services.market_insights import MarketInsightService
from app.services.matching import MatchingService
from app.services.mcp_connections import MCPConnectionService
from app.services.quick_matching import QuickMatchingService
from app.services.ranking import RankingService
from app.services.ranking_runs import RankingRunService
from app.services.recruitment_search import RecruitmentSearchService
from app.services.resumes import ResumeService


def get_job_service(session: AsyncSession = Depends(get_db)) -> JobService:
    return JobService(session)


def get_recruitment_provider_registry(
    session: AsyncSession = Depends(get_db),
) -> RecruitmentProviderRegistry:
    return RecruitmentProviderRegistry(session)


def get_recruitment_search_service(
    session: AsyncSession = Depends(get_db),
) -> RecruitmentSearchService:
    return RecruitmentSearchService(session)


async def get_llm_provider(
    session: AsyncSession = Depends(get_db),
) -> LLMProvider:
    return await LLMSettingsService(session).get_runtime_provider()


async def get_embedding_provider(
    session: AsyncSession = Depends(get_db),
) -> LLMProvider:
    return await LLMSettingsService(session).get_runtime_embedding_provider()


async def get_optional_embedding_provider(
    session: AsyncSession = Depends(get_db),
) -> LLMProvider | None:
    try:
        return await LLMSettingsService(session).get_runtime_embedding_provider()
    except Exception:
        return None


def get_llm_settings_service(
    session: AsyncSession = Depends(get_db),
) -> LLMSettingsService:
    return LLMSettingsService(session)


def get_resume_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_embedding_provider),
) -> ResumeService:
    return ResumeService(session, embedding_provider=provider)


def get_matching_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
    embedding_provider: LLMProvider = Depends(get_embedding_provider),
) -> MatchingService:
    return MatchingService(session, provider, embedding_provider=embedding_provider)


def get_quick_matching_service(session: AsyncSession = Depends(get_db)) -> QuickMatchingService:
    return QuickMatchingService(session)


def get_ranking_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
    embedding_provider: LLMProvider = Depends(get_embedding_provider),
) -> RankingService:
    return RankingService(session, provider, embedding_provider=embedding_provider)


def get_ranking_run_service(
    session: AsyncSession = Depends(get_db),
) -> RankingRunService:
    return RankingRunService(session)


def get_campaign_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> CampaignService:
    return CampaignService(session, provider)


def get_agent_runtime(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
    embedding_provider: LLMProvider = Depends(get_embedding_provider),
) -> AgentRuntime:
    return AgentRuntime(session, provider, embedding_provider=embedding_provider)


def get_career_advisor_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
    embedding_provider: LLMProvider | None = Depends(get_optional_embedding_provider),
) -> CareerAdvisorService:
    return CareerAdvisorService(session, provider, embedding_provider=embedding_provider)


def get_career_memory_service(
    session: AsyncSession = Depends(get_db),
    embedding_provider: LLMProvider | None = Depends(get_optional_embedding_provider),
) -> CareerMemoryService:
    return CareerMemoryService(session, embedding_provider=embedding_provider)


def get_mcp_connection_service(
    session: AsyncSession = Depends(get_db),
) -> MCPConnectionService:
    return MCPConnectionService(session)


def get_evaluation_service(
    session: AsyncSession = Depends(get_db),
) -> EvaluationService:
    return EvaluationService(session)


def get_browser_task_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_llm_provider),
) -> BrowserTaskService:
    return BrowserTaskService(session, provider)


def get_dashboard_service(session: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(DashboardRepository(session))


def get_market_insight_service(
    session: AsyncSession = Depends(get_db),
) -> MarketInsightService:
    return MarketInsightService(session)


def get_knowledge_index_service(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider = Depends(get_embedding_provider),
) -> KnowledgeIndexService:
    return KnowledgeIndexService(session, provider)


def get_job_knowledge_rag(
    session: AsyncSession = Depends(get_db),
    provider: LLMProvider | None = Depends(get_optional_embedding_provider),
) -> JobKnowledgeRAG:
    return JobKnowledgeRAG(session, provider)
