from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.models.states import CampaignJobStatus
from app.repositories.campaigns import CampaignRepository
from app.repositories.matching import MatchingRepository
from app.schemas.agent_tools import (
    AnalyzeJobsInput,
    AnalyzeJobsOutput,
    CreateCampaignToolInput,
    CreateCampaignToolOutput,
    GetJobInput,
    GetJobOutput,
    QueueApplicationInput,
    QueueApplicationOutput,
    RankedToolJob,
    RankJobsToolInput,
    RankJobsToolOutput,
    RequestApprovalInput,
    RequestApprovalOutput,
    RetrieveResumeInput,
    RetrieveResumeOutput,
    ScoreJobToolInput,
    ScoreJobToolOutput,
    SearchJobsInput,
    SearchJobsOutput,
    ToolJob,
)
from app.schemas.campaigns import CampaignApproveRequest, CampaignCreate
from app.schemas.ranking import JobRankingRequest
from app.schemas.resumes import ResumeProfile
from app.services.campaigns import CampaignService
from app.services.jobs import JobService
from app.services.matching import MatchingResumeNotFoundError, MatchingService
from app.services.ranking import RankingService
from app.services.ranking_runs import RankingRunService

ToolHandler = Callable[[BaseModel], Awaitable[BaseModel]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: ToolHandler

    async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        parsed_input = self.input_schema.model_validate(payload)
        raw_output = await self.handler(parsed_input)
        output = self.output_schema.model_validate(raw_output)
        return output.model_dump(mode="json")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool: {name}") from exc

    def catalog(self) -> list[AgentTool]:
        return list(self._tools.values())


class AgentToolService:
    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings or get_settings()
        self.campaign_repository = CampaignRepository(session)
        self.matching_repository = MatchingRepository(session)

    def registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        definitions = [
            AgentTool(
                "search_jobs",
                "Search normalized jobs by keywords and cities.",
                SearchJobsInput,
                SearchJobsOutput,
                self.search_jobs,
            ),
            AgentTool(
                "get_job",
                "Load one normalized job.",
                GetJobInput,
                GetJobOutput,
                self.get_job,
            ),
            AgentTool(
                "analyze_job",
                "Analyze and normalize a batch of jobs.",
                AnalyzeJobsInput,
                AnalyzeJobsOutput,
                self.analyze_jobs,
            ),
            AgentTool(
                "retrieve_resume",
                "Load the selected resume profile and retrieval inventory.",
                RetrieveResumeInput,
                RetrieveResumeOutput,
                self.retrieve_resume,
            ),
            AgentTool(
                "score_job",
                "Score one job against a resume with Resume RAG.",
                ScoreJobToolInput,
                ScoreJobToolOutput,
                self.score_job,
            ),
            AgentTool(
                "rank_jobs",
                "Run the cost-aware multi-stage Ranking Pipeline.",
                RankJobsToolInput,
                RankJobsToolOutput,
                self.rank_jobs,
            ),
            AgentTool(
                "create_campaign",
                "Create and start a Campaign from the requested criteria.",
                CreateCampaignToolInput,
                CreateCampaignToolOutput,
                self.create_campaign,
            ),
            AgentTool(
                "queue_application",
                "Approve selected Campaign jobs and queue their Applications.",
                QueueApplicationInput,
                QueueApplicationOutput,
                self.queue_application,
            ),
            AgentTool(
                "request_approval",
                "Pause execution and request explicit user approval.",
                RequestApprovalInput,
                RequestApprovalOutput,
                self.request_approval,
            ),
        ]
        for tool in definitions:
            registry.register(tool)
        return registry

    async def search_jobs(self, raw_input: BaseModel) -> SearchJobsOutput:
        payload = SearchJobsInput.model_validate(raw_input)
        jobs = await self.campaign_repository.search_jobs(
            keywords=payload.keywords,
            cities=payload.cities,
            limit=payload.limit,
        )
        summaries = [
            ToolJob(id=job.id, title=job.title, location=job.location, platform=job.platform)
            for job in jobs
        ]
        return SearchJobsOutput(
            count=len(jobs),
            job_ids=[job.id for job in jobs],
            jobs=summaries,
        )

    async def get_job(self, raw_input: BaseModel) -> GetJobOutput:
        payload = GetJobInput.model_validate(raw_input)
        job = await JobService(self.session).get_job(payload.job_id)
        if job is None:
            return GetJobOutput(found=False)
        return GetJobOutput(
            found=True,
            job=ToolJob(
                id=job.id,
                title=job.title,
                location=job.location,
                platform=job.platform,
            ),
            description=job.description,
        )

    async def analyze_jobs(self, raw_input: BaseModel) -> AnalyzeJobsOutput:
        payload = AnalyzeJobsInput.model_validate(raw_input)
        analyzed = []
        service = JobService(self.session)
        for job_id in payload.job_ids:
            job = await service.analyze_job(job_id)
            if job is not None:
                await self.session.refresh(job, attribute_names=["skills"])
                analyzed.append(job_id)
        return AnalyzeJobsOutput(analyzed_count=len(analyzed), job_ids=analyzed)

    async def retrieve_resume(self, raw_input: BaseModel) -> RetrieveResumeOutput:
        payload = RetrieveResumeInput.model_validate(raw_input)
        resume = (
            await self.matching_repository.get_resume(payload.resume_id)
            if payload.resume_id
            else await self.matching_repository.get_default_resume()
        )
        if resume is None:
            raise MatchingResumeNotFoundError("Upload or select a resume before running the agent")
        profile = ResumeProfile.model_validate(resume.structured_profile or {})
        return RetrieveResumeOutput(
            resume_id=resume.id,
            name=resume.name,
            skills=profile.skills,
            chunk_count=len(resume.chunks),
        )

    async def score_job(self, raw_input: BaseModel) -> ScoreJobToolOutput:
        payload = ScoreJobToolInput.model_validate(raw_input)
        score = await MatchingService(self.session, self.provider, self.settings).score(
            job_id=payload.job_id,
            resume_id=payload.resume_id,
        )
        return ScoreJobToolOutput(
            job_id=payload.job_id,
            final_score=score.final_score,
            recommendation=score.recommendation,
            reasoning_summary=score.reasoning_summary,
        )

    async def rank_jobs(self, raw_input: BaseModel) -> RankJobsToolOutput:
        payload = RankJobsToolInput.model_validate(raw_input)
        if not payload.job_ids:
            return RankJobsToolOutput(count=0, candidates=[])
        result = await RankingService(self.session, self.provider, self.settings).rank(
            JobRankingRequest(
                resume_id=payload.resume_id,
                job_ids=payload.job_ids,
                candidate_limit=min(len(payload.job_ids), self.settings.ranking_candidate_limit),
                top_k_embedding=max(self.settings.top_k_embedding, payload.final_top_k),
                top_k_rerank=max(self.settings.top_k_rerank, payload.final_top_k),
                top_k_llm=max(self.settings.top_k_llm, payload.final_top_k),
                final_top_k=payload.final_top_k,
            )
        )
        candidates = [
            RankedToolJob(
                job_id=item.job.id,
                title=item.job.title,
                score=item.score.final_score,
                recommendation=item.score.recommendation,
                score_id=item.score.id,
            )
            for item in result.items
            if item.score.final_score >= payload.min_score
        ]
        return RankJobsToolOutput(
            count=len(candidates),
            candidates=candidates,
            trace_run_id=result.trace.run_id,
            token_usage=result.trace.token_usage,
        )

    async def create_campaign(self, raw_input: BaseModel) -> CreateCampaignToolOutput:
        payload = CreateCampaignToolInput.model_validate(raw_input)
        service = CampaignService(self.session, self.provider, self.settings)
        campaign = await service.create(
            CampaignCreate(
                name=payload.name,
                resume_id=payload.resume_id,
                keywords=payload.keywords,
                min_score=payload.min_score,
                max_jobs=payload.max_jobs,
                target_cities=payload.cities,
            )
        )
        campaign, ranking_run = await service.start(campaign.id)
        if ranking_run is not None:
            await RankingRunService(self.session).execute(ranking_run.id, self.provider)
            campaign = await service.get_campaign(campaign.id)
        score_ids = {
            item.job_id: item.application_metadata.get("ranking_score_id")
            for item in campaign.applications
        }
        return CreateCampaignToolOutput(
            campaign_id=campaign.id,
            status=campaign.status,
            candidates=[
                RankedToolJob(
                    job_id=item.job_id,
                    title=item.job.title,
                    score=item.score,
                    recommendation="apply" if item.score >= 70 else "maybe",
                    score_id=score_ids.get(item.job_id),
                )
                for item in sorted(campaign.campaign_jobs, key=lambda value: value.rank)
            ],
        )

    async def queue_application(self, raw_input: BaseModel) -> QueueApplicationOutput:
        payload = QueueApplicationInput.model_validate(raw_input)
        campaign = await CampaignService(
            self.session, self.provider, self.settings
        ).approve(
            payload.campaign_id,
            CampaignApproveRequest(job_ids=payload.job_ids),
        )
        return QueueApplicationOutput(
            campaign_id=campaign.id,
            queued_count=sum(
                item.status == CampaignJobStatus.QUEUED.value
                for item in campaign.campaign_jobs
            ),
            status=campaign.status,
        )

    async def request_approval(self, raw_input: BaseModel) -> RequestApprovalOutput:
        payload = RequestApprovalInput.model_validate(raw_input)
        return RequestApprovalOutput(
            campaign_id=payload.campaign_id,
            candidate_count=len(payload.candidates),
            prompt=payload.prompt,
            candidates=payload.candidates,
        )
