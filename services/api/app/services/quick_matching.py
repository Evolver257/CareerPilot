from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job, JobScore, Resume, UserPreference
from app.repositories.matching import MatchingRepository
from app.schemas.matching import QuickScoreBatchResponse, QuickScoreRead, Recommendation
from app.schemas.resumes import ResumeProfile
from app.services.matching import (
    EducationMatcher,
    ExperienceMatcher,
    PreferenceScorer,
    RulesFilter,
    SkillCoverage,
)


class QuickMatchingJobNotFoundError(ValueError):
    """Raised when a requested quick-score job does not exist."""


class QuickMatchingResumeNotFoundError(ValueError):
    """Raised when no requested or default resume exists."""


class QuickMatchingService:
    """Cheap deterministic matching for incremental job discovery.

    This intentionally does not retrieve embeddings or call an LLM. It is used
    only to decide the initial selection state while a user is collecting jobs;
    the existing deep ranking flow remains the source of detailed judgments.
    """

    SCORE_VERSION = "QUICK_MATCH_V1"
    WEIGHTS = {
        "skill": 0.45,
        "education": 0.20,
        "experience": 0.15,
        "keyword": 0.15,
        "preference": 0.05,
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = MatchingRepository(session)
        self.rules = RulesFilter()
        self.skill_coverage = SkillCoverage()
        self.education_matcher = EducationMatcher()
        self.experience_matcher = ExperienceMatcher()
        self.preference_scorer = PreferenceScorer()

    async def score_many(
        self,
        *,
        job_ids: list[UUID],
        resume_id: UUID | None,
    ) -> QuickScoreBatchResponse:
        requested_ids = list(dict.fromkeys(job_ids))
        jobs = await self.repository.get_jobs(requested_ids)
        jobs_by_id = {job.id: job for job in jobs}
        missing = [job_id for job_id in requested_ids if job_id not in jobs_by_id]
        if missing:
            raise QuickMatchingJobNotFoundError("One or more jobs do not exist")

        resume = (
            await self.repository.get_resume(resume_id)
            if resume_id
            else await self.repository.get_default_resume()
        )
        if resume is None:
            raise QuickMatchingResumeNotFoundError(
                "Upload or select a resume before quick scoring"
            )
        preferences = await self.repository.get_preferences(resume.user_id)

        results: list[QuickScoreRead] = []
        new_scores: list[JobScore] = []
        for job_id in requested_ids:
            job = jobs_by_id[job_id]
            fingerprint = self._fingerprint(job, resume, preferences)
            cached = await self.repository.get_latest_score(
                job_id=job.id,
                resume_id=resume.id,
                score_version=self.SCORE_VERSION,
                input_fingerprint=fingerprint,
                judge_sources=("deterministic",),
            )
            if cached is not None:
                results.append(self._read(cached, cached=True))
                continue

            score = self._build_score(job, resume, preferences, fingerprint)
            new_scores.append(score)
            results.append(self._read(score, cached=False))

        if new_scores:
            self.session.add_all(new_scores)
            await self.session.commit()
            for score in new_scores:
                await self.session.refresh(score)

        return QuickScoreBatchResponse(items=results)

    def _build_score(
        self,
        job: Job,
        resume: Resume,
        preferences: UserPreference | None,
        fingerprint: str,
    ) -> JobScore:
        profile = ResumeProfile.model_validate(resume.structured_profile or {})
        rule_result = self.rules.evaluate(job, preferences)
        skill_result = self.skill_coverage.score(job, profile, resume_text=resume.raw_text)
        education_score = self.education_matcher.score(
            job.education_requirement or "", profile
        )
        experience_score = self.experience_matcher.score(
            job.experience_requirement or "", profile
        )
        keyword_score = self._keyword_score(job, resume)
        preference_score = self.preference_scorer.preference_score(job, preferences)
        score_inputs = {
            "skill": skill_result.score,
            "education": education_score,
            "experience": experience_score,
            "keyword": keyword_score,
            "preference": preference_score,
        }
        final_score = round(
            sum(self.WEIGHTS[key] * value for key, value in score_inputs.items()),
            2,
        )
        if not rule_result.passed:
            final_score = min(final_score, 25.0)

        missing = list(skill_result.missing)
        strengths = [
            "匹配技能：" + "、".join(skill_result.matched[:8])
        ] if skill_result.matched else []
        gaps = ["缺少要求技能：" + "、".join(missing)] if missing else []
        recommendation = self._recommendation(final_score)
        reasoning = (
            f"快速评分（不调用 LLM）：技能 {skill_result.score:.0f} 分，"
            f"学历 {education_score:.0f} 分，经历 {experience_score:.0f} 分，"
            f"关键词 {keyword_score:.0f} 分。"
        )
        return JobScore(
            job_id=job.id,
            resume_id=resume.id,
            semantic_score=keyword_score,
            skill_score=skill_result.score,
            education_score=education_score,
            experience_score=experience_score,
            location_score=100.0,
            preference_score=preference_score,
            llm_score=0.0,
            final_score=final_score,
            rules_passed=rule_result.passed,
            rule_reasons=rule_result.reasons,
            matched_skills=skill_result.matched,
            missing_skills=missing,
            strengths=strengths,
            gaps=gaps,
            risks=list(rule_result.reasons),
            resume_evidence=[],
            recommendation=recommendation,
            reasoning_summary=reasoning,
            score_version=self.SCORE_VERSION,
            input_fingerprint=fingerprint,
            judge_source="deterministic",
            weights=self.WEIGHTS,
        )

    @staticmethod
    def _keyword_score(job: Job, resume: Resume) -> float:
        normalized = job.normalized_data or {}
        structured = normalized.get("structured_job", {})
        if not isinstance(structured, dict):
            structured = {}
        terms: list[str] = [job.title]
        for key in ("required_skills", "preferred_skills", "keywords"):
            values = structured.get(key, [])
            if isinstance(values, list):
                terms.extend(str(value) for value in values)
        terms.extend(skill.skill_name for skill in job.skills)
        terms = list(dict.fromkeys(value.strip() for value in terms if value.strip()))
        if not terms:
            return 50.0
        resume_text = (resume.raw_text or "").casefold()
        hits = sum(1 for term in terms if term.casefold() in resume_text)
        return round(hits / len(terms) * 100, 2)

    @staticmethod
    def _recommendation(score: float) -> Recommendation:
        if score >= 85:
            return "strong_apply"
        if score >= 70:
            return "apply"
        if score >= 50:
            return "maybe"
        return "skip"

    @classmethod
    def _fingerprint(
        cls,
        job: Job,
        resume: Resume,
        preferences: UserPreference | None,
    ) -> str:
        preference_data = {
            "target_roles": preferences.target_roles if preferences else [],
            "target_cities": preferences.target_cities if preferences else [],
            "preferred_keywords": preferences.preferred_keywords if preferences else [],
            "required_keywords": preferences.required_keywords if preferences else [],
            "excluded_keywords": preferences.excluded_keywords if preferences else [],
            "blocked_companies": preferences.blocked_companies if preferences else [],
        }
        payload = {
            "version": cls.SCORE_VERSION,
            "job_id": str(job.id),
            "job_content_hash": job.content_hash,
            "job_updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "resume_id": str(resume.id),
            "resume_version": resume.version,
            "resume_updated_at": resume.updated_at.isoformat() if resume.updated_at else None,
            "preference": preference_data,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _read(score: JobScore, *, cached: bool) -> QuickScoreRead:
        return QuickScoreRead(
            job_id=score.job_id,
            resume_id=score.resume_id,
            score=score.final_score,
            rules_passed=score.rules_passed,
            rule_reasons=score.rule_reasons,
            matched_skills=score.matched_skills,
            missing_skills=score.missing_skills,
            recommendation=score.recommendation,
            reasoning_summary=score.reasoning_summary,
            cached=cached,
        )
