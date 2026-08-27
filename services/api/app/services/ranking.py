from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.models.entities import Job, JobScore, Resume
from app.repositories.matching import MatchingRepository
from app.repositories.ranking import RankingRepository
from app.schemas.jobs import JobRead
from app.schemas.matching import JobScoreRead, LLMJudgeOutput, ResumeEvidenceRead
from app.schemas.ranking import (
    JobRankingRequest,
    JobRankingResponse,
    RankedJobRead,
    RankingConfigRead,
    RankingStageName,
    RankingTraceCandidate,
    RankingTraceRead,
    RankingTraceStage,
)
from app.schemas.resumes import ResumeProfile
from app.services.jobs import JobService
from app.services.matching import (
    EducationMatcher,
    ExperienceMatcher,
    LLMJudge,
    MatchingResumeNotFoundError,
    PreferenceScorer,
    RuleResult,
    RulesFilter,
    SkillCoverage,
    SkillCoverageResult,
)
from app.services.resume_rag import ResumeRAG
from app.services.score_cache import build_score_fingerprint

RankingProgressCallback = Callable[[str, int, int, int, int, int, int], Awaitable[None]]
RankingCandidateCallback = Callable[[Job, JobScore, int, int], Awaitable[None]]


@dataclass
class RankingCandidate:
    job: Job
    rule: RuleResult | None = None
    evidence: list[ResumeEvidenceRead] = field(default_factory=list)
    semantic_score: float = 0.0
    skill: SkillCoverageResult | None = None
    education_score: float = 0.0
    experience_score: float = 0.0
    location_score: float = 0.0
    preference_score: float = 0.0
    rerank_score: float = 0.0
    judge: LLMJudgeOutput | None = None
    judge_source: str = "llm"
    input_fingerprint: str | None = None
    cached_score: JobScore | None = None
    final_score: float = 0.0

    @property
    def sub_scores(self) -> dict[str, float]:
        return {
            "semantic": self.semantic_score,
            "skill": self.skill.score if self.skill else 0.0,
            "education": self.education_score,
            "experience": self.experience_score,
            "location": self.location_score,
            "preference": self.preference_score,
        }


class RankingService:
    """Cost-aware multi-stage job ranking with an inspectable decision trace."""

    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        settings: Settings | None = None,
        embedding_provider: LLMProvider | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings or get_settings()
        self.repository = RankingRepository(session)
        self.matching_repository = MatchingRepository(session)
        self.embedding_provider = embedding_provider or provider
        self.rag = ResumeRAG(self.matching_repository, self.embedding_provider, self.settings)
        self.rules = RulesFilter()
        self.skill_coverage = SkillCoverage()
        self.education_matcher = EducationMatcher()
        self.experience_matcher = ExperienceMatcher()
        self.preference_scorer = PreferenceScorer()
        self.llm_judge = LLMJudge(provider)

    async def rank(
        self,
        payload: JobRankingRequest,
        progress: RankingProgressCallback | None = None,
        candidate_completed: RankingCandidateCallback | None = None,
    ) -> JobRankingResponse:
        started_at = datetime.now(UTC)
        config = self._effective_config(payload)
        await self._report(progress, "loading_candidates", 2, 0, 0, 0, 0, 0)
        jobs = await self.repository.list_candidates(
            limit=config.candidate_limit,
            job_ids=payload.job_ids,
            search=payload.search,
        )
        jobs = await self._ensure_analyzed(jobs)
        resume = await self._resolve_resume(payload.resume_id)
        profile = ResumeProfile.model_validate(resume.structured_profile or {})
        preferences = await self.matching_repository.get_preferences(resume.user_id)
        candidates = [RankingCandidate(job=job) for job in jobs]
        stages: list[RankingTraceStage] = []
        await self._report(
            progress, "rule_filter", 8, 0, len(candidates), 0, 0, 0
        )

        stage_started = perf_counter()
        eligible: list[RankingCandidate] = []
        for candidate in candidates:
            candidate.rule = self.rules.evaluate(candidate.job, preferences)
            if candidate.rule.passed:
                eligible.append(candidate)
        stages.append(
            RankingTraceStage(
                name="rule_filter",
                input_count=len(candidates),
                output_count=len(eligible),
                duration_ms=self._duration_ms(stage_started),
                candidates=[
                    self._snapshot(
                        candidate,
                        rank=index,
                        selected=bool(candidate.rule and candidate.rule.passed),
                        passed=bool(candidate.rule and candidate.rule.passed),
                        reasons=candidate.rule.reasons if candidate.rule else [],
                    )
                    for index, candidate in enumerate(candidates, start=1)
                ],
            )
        )
        await self._report(
            progress, "embedding_rank", 20, 0, len(candidates), 0, 0, 0
        )

        stage_started = perf_counter()
        for candidate in eligible:
            candidate.evidence = await self.rag.retrieve(candidate.job, resume)
            candidate.semantic_score = self.rag.semantic_score(candidate.evidence)
        embedding_ranked = self._sort(eligible, "semantic_score")
        embedding_selected = embedding_ranked[: config.top_k_embedding]
        stages.append(
            self._scored_stage(
                name="embedding_rank",
                candidates=embedding_ranked,
                selected_count=len(embedding_selected),
                score_name="semantic_score",
                stage_started=stage_started,
            )
        )
        await self._report(
            progress, "reranker", 40, 0, len(candidates), 0, 0, 0
        )

        stage_started = perf_counter()
        for candidate in embedding_selected:
            candidate.skill = self.skill_coverage.score(candidate.job, profile)
            candidate.education_score = self.education_matcher.score(
                candidate.job.education_requirement or "", profile
            )
            candidate.experience_score = self.experience_matcher.score(
                candidate.job.experience_requirement or "", profile
            )
            candidate.location_score = self.preference_scorer.location_score(
                candidate.job, preferences
            )
            candidate.preference_score = self.preference_scorer.preference_score(
                candidate.job, preferences
            )
            candidate.rerank_score = self._rerank_score(candidate.sub_scores)
        reranked = self._sort(embedding_selected, "rerank_score")
        rerank_selected = reranked[: config.top_k_rerank]
        stages.append(
            self._scored_stage(
                name="reranker",
                candidates=reranked,
                selected_count=len(rerank_selected),
                score_name="rerank_score",
                stage_started=stage_started,
            )
        )

        stage_started = perf_counter()
        use_llm = config.scoring_mode == "llm"
        weights = self._normalized_weights(use_llm=use_llm)
        cache_hits = 0
        llm_calls = 0
        score_by_job: dict[UUID, JobScore] = {}
        scoring_stage: RankingStageName = "llm_judge" if use_llm else "deterministic_rank"
        await self._report(
            progress, scoring_stage, 50, 0, len(rerank_selected), 0, 0, 0
        )
        for index, candidate in enumerate(rerank_selected, start=1):
            skill = candidate.skill or SkillCoverageResult(0.0, [], [])
            candidate.input_fingerprint = build_score_fingerprint(
                job=candidate.job,
                resume=resume,
                provider=self.provider,
                embedding_provider=self.embedding_provider,
                score_version=self.settings.ranking_version,
                weights=weights,
            )
            candidate.cached_score = await self.matching_repository.get_latest_score(
                job_id=candidate.job.id,
                resume_id=resume.id,
                score_version=self.settings.ranking_version,
                input_fingerprint=candidate.input_fingerprint,
                judge_sources=self._cacheable_judge_sources(config.scoring_mode),
            )
            if candidate.cached_score is not None:
                cache_hits += 1
                candidate.judge = self._judge_from_score(candidate.cached_score)
                candidate.judge_source = candidate.cached_score.judge_source
                candidate.final_score = candidate.cached_score.final_score
                score_by_job[candidate.job.id] = candidate.cached_score
            else:
                if use_llm:
                    llm_calls += 1
                    candidate.judge = await self.llm_judge.judge(
                        job=candidate.job,
                        required_skills=[
                            item.skill_name
                            for item in candidate.job.skills
                            if item.skill_type == "required"
                        ],
                        matched_skills=skill.matched,
                        missing_skills=skill.missing,
                        evidence=candidate.evidence,
                        sub_scores=candidate.sub_scores,
                    )
                    candidate.judge_source = self.llm_judge.last_source
                    score_inputs = {**candidate.sub_scores, "llm": candidate.judge.score}
                else:
                    candidate.judge = LLMJudge._deterministic_judge(
                        matched_skills=skill.matched,
                        missing_skills=skill.missing,
                        evidence=candidate.evidence,
                        sub_scores=candidate.sub_scores,
                    )
                    candidate.judge_source = "deterministic"
                    score_inputs = candidate.sub_scores
                candidate.final_score = round(
                    sum(weights[key] * score_inputs[key] for key in weights),
                    2,
                )
                score = self._build_score(candidate, resume, weights)
                await self.matching_repository.add_score(score)
                score_by_job[candidate.job.id] = score
            if candidate_completed is not None:
                await candidate_completed(
                    candidate.job,
                    score_by_job[candidate.job.id],
                    index,
                    len(rerank_selected),
                )
            await self._report(
                progress,
                scoring_stage,
                50 + round(index / max(len(rerank_selected), 1) * 40),
                index,
                len(rerank_selected),
                cache_hits,
                llm_calls,
                self.llm_judge.fallback_count,
            )
        if use_llm:
            scored_ranked = sorted(
                rerank_selected,
                key=lambda item: (
                    -(item.judge.score if item.judge else 0.0),
                    -item.rerank_score,
                    item.job.title.casefold(),
                    str(item.job.id),
                ),
            )
            stage_score_name = "llm_score"
        else:
            scored_ranked = self._sort(rerank_selected, "final_score")
            stage_score_name = "final_score"
        scored_selected = scored_ranked[: config.top_k_llm]
        stages.append(
            self._scored_stage(
                name=scoring_stage,
                candidates=scored_ranked,
                selected_count=len(scored_selected),
                score_name=stage_score_name,
                stage_started=stage_started,
            )
        )

        stage_started = perf_counter()
        final_ranked = self._sort(scored_selected, "final_score")
        finalists = final_ranked[: config.final_top_k]
        scores = [score_by_job[candidate.job.id] for candidate in finalists]
        stages.append(
            self._scored_stage(
                name="final_ranking",
                candidates=final_ranked,
                selected_count=len(finalists),
                score_name="final_score",
                stage_started=stage_started,
            )
        )
        await self._report(
            progress,
            "final_ranking",
            100,
            len(rerank_selected),
            len(rerank_selected),
            cache_hits,
            llm_calls,
            self.llm_judge.fallback_count,
        )

        completed_at = datetime.now(UTC)
        trace = RankingTraceRead(
            run_id=uuid4(),
            version=self.settings.ranking_version,
            started_at=started_at,
            completed_at=completed_at,
            llm_calls=llm_calls,
            cache_hits=cache_hits,
            fallback_count=self.llm_judge.fallback_count,
            token_usage=self.llm_judge.usage.as_dict(),
            config=config,
            stages=stages,
        )
        return JobRankingResponse(
            items=[
                RankedJobRead(
                    rank=index,
                    job=JobRead.model_validate(candidate.job),
                    score=JobScoreRead.model_validate(score),
                )
                for index, (candidate, score) in enumerate(
                    zip(finalists, scores, strict=True), start=1
                )
            ],
            total_candidates=len(candidates),
            trace=trace,
        )

    async def _resolve_resume(self, resume_id: UUID | None) -> Resume:
        resume = (
            await self.matching_repository.get_resume(resume_id)
            if resume_id
            else await self.matching_repository.get_default_resume()
        )
        if resume is None:
            raise MatchingResumeNotFoundError("Upload or select a resume before ranking")
        return resume

    async def _ensure_analyzed(self, jobs: list[Job]) -> list[Job]:
        ready: list[Job] = []
        job_service = JobService(self.session)
        for job in jobs:
            if (
                (job.normalized_data or {}).get("analysis_version")
                != JobService.CURRENT_ANALYSIS_VERSION
                or not (job.normalized_data or {}).get("structured_job")
                or not job.skills
            ):
                await job_service.analyze_job(job.id)
                refreshed = await self.matching_repository.get_job(job.id)
                if refreshed is not None:
                    job = refreshed
            ready.append(job)
        return ready

    def _build_score(
        self,
        candidate: RankingCandidate,
        resume: Resume,
        weights: dict[str, float],
    ) -> JobScore:
        skill = candidate.skill or SkillCoverageResult(0.0, [], [])
        judge = candidate.judge or LLMJudgeOutput()
        return JobScore(
            job_id=candidate.job.id,
            resume_id=resume.id,
            semantic_score=candidate.semantic_score,
            skill_score=skill.score,
            education_score=candidate.education_score,
            experience_score=candidate.experience_score,
            location_score=candidate.location_score,
            preference_score=candidate.preference_score,
            llm_score=0.0 if candidate.judge_source == "deterministic" else judge.score,
            final_score=candidate.final_score,
            rules_passed=True,
            rule_reasons=[],
            matched_skills=skill.matched,
            missing_skills=skill.missing,
            strengths=judge.strengths,
            gaps=judge.gaps,
            risks=judge.risks,
            resume_evidence=[item.model_dump(mode="json") for item in candidate.evidence],
            recommendation=judge.recommendation,
            reasoning_summary=judge.reasoning_summary,
            score_version=self.settings.ranking_version,
            input_fingerprint=candidate.input_fingerprint,
            judge_source=candidate.judge_source,
            weights=weights,
        )

    @staticmethod
    def _judge_from_score(score: JobScore) -> LLMJudgeOutput:
        return LLMJudgeOutput(
            score=score.llm_score,
            strengths=score.strengths,
            gaps=score.gaps,
            risks=score.risks,
            recommendation=score.recommendation,
            reasoning_summary=score.reasoning_summary,
        )

    @staticmethod
    async def _report(
        callback: RankingProgressCallback | None,
        stage: str,
        progress: int,
        processed: int,
        total: int,
        cache_hits: int,
        llm_calls: int,
        fallback_count: int,
    ) -> None:
        if callback is not None:
            await callback(
                stage,
                progress,
                processed,
                total,
                cache_hits,
                llm_calls,
                fallback_count,
            )

    def _effective_config(self, payload: JobRankingRequest) -> RankingConfigRead:
        candidate_limit = payload.candidate_limit or self.settings.ranking_candidate_limit
        embedding = min(payload.top_k_embedding or self.settings.top_k_embedding, candidate_limit)
        rerank = min(payload.top_k_rerank or self.settings.top_k_rerank, embedding)
        llm = (
            rerank
            if payload.scoring_mode == "fast"
            else min(payload.top_k_llm or self.settings.top_k_llm, rerank)
        )
        final = min(payload.final_top_k or self.settings.final_ranking_top_k, llm)
        if min(candidate_limit, embedding, rerank, llm, final) <= 0:
            raise ValueError("Ranking limits must be positive")
        return RankingConfigRead(
            candidate_limit=candidate_limit,
            top_k_embedding=embedding,
            top_k_rerank=rerank,
            top_k_llm=llm,
            final_top_k=final,
            scoring_mode=payload.scoring_mode,
        )

    def _rerank_score(self, sub_scores: dict[str, float]) -> float:
        weights = {
            key: value for key, value in self.settings.matching_weights.items() if key != "llm"
        }
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("Non-LLM matching weights must have a positive total")
        return round(sum(sub_scores[key] * value / total for key, value in weights.items()), 2)

    def _normalized_weights(self, *, use_llm: bool = True) -> dict[str, float]:
        weights = self.settings.matching_weights
        if not use_llm:
            weights = {key: value for key, value in weights.items() if key != "llm"}
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("Matching weights must have a positive total")
        return {key: value / total for key, value in weights.items()}

    def _cacheable_judge_sources(self, scoring_mode: str) -> tuple[str, ...]:
        if scoring_mode == "fast":
            return ("deterministic",)
        if getattr(self.provider, "provider_name", None) == "mock":
            return ("llm", "fallback")
        return ("llm",)

    @staticmethod
    def _sort(candidates: list[RankingCandidate], score_name: str) -> list[RankingCandidate]:
        return sorted(
            candidates,
            key=lambda item: (
                -float(getattr(item, score_name)),
                item.job.title.casefold(),
                str(item.job.id),
            ),
        )

    def _scored_stage(
        self,
        *,
        name: RankingStageName,
        candidates: list[RankingCandidate],
        selected_count: int,
        score_name: str,
        stage_started: float,
    ) -> RankingTraceStage:
        return RankingTraceStage(
            name=name,
            input_count=len(candidates),
            output_count=selected_count,
            duration_ms=self._duration_ms(stage_started),
            candidates=[
                self._snapshot(
                    candidate,
                    rank=index,
                    selected=index <= selected_count,
                    score=self._stage_score(candidate, score_name),
                )
                for index, candidate in enumerate(candidates, start=1)
            ],
        )

    @staticmethod
    def _stage_score(candidate: RankingCandidate, score_name: str) -> float:
        if score_name == "llm_score":
            return candidate.judge.score if candidate.judge else 0.0
        return float(getattr(candidate, score_name))

    @staticmethod
    def _snapshot(
        candidate: RankingCandidate,
        *,
        rank: int,
        selected: bool,
        score: float | None = None,
        passed: bool | None = None,
        reasons: list[str] | None = None,
    ) -> RankingTraceCandidate:
        return RankingTraceCandidate(
            job_id=candidate.job.id,
            title=candidate.job.title,
            rank=rank,
            score=round(score, 2) if score is not None else None,
            selected=selected,
            passed=passed,
            reasons=reasons or [],
            sub_scores={key: round(value, 2) for key, value in candidate.sub_scores.items()},
            recommendation=candidate.judge.recommendation if candidate.judge else None,
        )

    @staticmethod
    def _duration_ms(started: float) -> float:
        return round((perf_counter() - started) * 1000, 2)
