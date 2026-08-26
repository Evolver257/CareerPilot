from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.llm.prompts.job_judge import build_job_judge_prompt
from app.llm.provider import LLMProvider, LLMProviderError
from app.llm.usage import UsageAccumulator, UsageRecord, estimate_tokens
from app.models.entities import Job, JobScore, UserPreference
from app.repositories.matching import MatchingRepository
from app.schemas.job_intelligence import StructuredJob
from app.schemas.matching import LLMJudgeOutput, ResumeEvidenceRead
from app.schemas.resumes import ResumeProfile
from app.services.jobs import JobService
from app.services.resume_rag import ResumeRAG
from app.services.score_cache import build_score_fingerprint

logger = logging.getLogger(__name__)


class MatchingJobNotFoundError(ValueError):
    """Raised when a job cannot be scored."""


class MatchingResumeNotFoundError(ValueError):
    """Raised when no requested or default resume exists."""


@dataclass(frozen=True)
class RuleResult:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class SkillCoverageResult:
    score: float
    matched: list[str]
    missing: list[str]


class RulesFilter:
    def evaluate(self, job: Job, preferences: UserPreference | None) -> RuleResult:
        if preferences is None:
            return RuleResult(True, [])
        text = f"{job.title}\n{job.description}".casefold()
        reasons: list[str] = []

        company_name = job.company.name.casefold() if job.company else ""
        blocked = {value.casefold() for value in preferences.blocked_companies}
        if company_name and company_name in blocked:
            reasons.append(f"Blocked company: {job.company.name}")

        for keyword in preferences.excluded_keywords:
            if keyword.casefold() in text:
                reasons.append(f"Excluded keyword present: {keyword}")

        missing_required = [
            keyword for keyword in preferences.required_keywords if keyword.casefold() not in text
        ]
        if missing_required:
            reasons.append("Missing required keywords: " + ", ".join(missing_required))
        return RuleResult(not reasons, reasons)


class SkillCoverage:
    aliases = {
        "golang": "go",
        "nodejs": "node.js",
        "node": "node.js",
        "postgres": "postgresql",
        "js": "javascript",
        "ts": "typescript",
        "ml": "machine learning",
    }

    def score(
        self, job: Job, profile: ResumeProfile, *, resume_text: str = ""
    ) -> SkillCoverageResult:
        resume_map = {self._canonical(skill): skill for skill in profile.skills}
        required = self._unique(
            skill.skill_name for skill in job.skills if skill.skill_type == "required"
        )
        preferred = self._unique(
            skill.skill_name for skill in job.skills if skill.skill_type == "preferred"
        )
        all_job_skills = required + [skill for skill in preferred if skill not in required]
        for skill in all_job_skills:
            if self._appears_in_text(skill, resume_text):
                resume_map.setdefault(self._canonical(skill), skill)
        if "mysql" in resume_map or "postgresql" in resume_map:
            resume_map.setdefault("sql", "SQL")
        matched = [skill for skill in all_job_skills if self._canonical(skill) in resume_map]
        missing = [skill for skill in required if self._canonical(skill) not in resume_map]

        if not all_job_skills:
            return SkillCoverageResult(50.0, [], [])
        required_ratio = self._ratio(required, resume_map)
        preferred_ratio = self._ratio(preferred, resume_map)
        if required and preferred:
            score = 80 * required_ratio + 20 * preferred_ratio
        elif required:
            score = 100 * required_ratio
        else:
            score = 100 * preferred_ratio
        return SkillCoverageResult(round(score, 2), matched, missing)

    @classmethod
    def _canonical(cls, skill: str) -> str:
        normalized = re.sub(r"[^a-z0-9+#.]", "", skill.casefold())
        return cls.aliases.get(normalized, normalized)

    @classmethod
    def _ratio(cls, skills: list[str], resume_map: dict[str, str]) -> float:
        if not skills:
            return 1.0
        return sum(cls._canonical(skill) in resume_map for skill in skills) / len(skills)

    @classmethod
    def _appears_in_text(cls, skill: str, text: str) -> bool:
        if not text:
            return False
        canonical = cls._canonical(skill)
        variants = {skill, canonical, *(
            alias for alias, target in cls.aliases.items() if target == canonical
        )}
        return any(
            re.search(rf"(?<!\w){re.escape(variant.casefold())}(?!\w)", text.casefold())
            for variant in variants
            if variant
        )

    @staticmethod
    def _unique(values) -> list[str]:
        return list(dict.fromkeys(values))


class EducationMatcher:
    levels = {
        "high_school": 1,
        "associate": 2,
        "bachelor": 3,
        "master": 4,
        "phd": 5,
    }

    def score(self, requirement: str, profile: ResumeProfile) -> float:
        required_level = self._level(requirement)
        if required_level == 0:
            return 100.0
        education_text = " ".join(
            str(item.model_dump(exclude_none=True)) for item in profile.education
        )
        candidate_level = self._level(education_text)
        if candidate_level >= required_level:
            return 100.0
        if candidate_level > 0:
            return 45.0
        if profile.education:
            return 70.0
        return 0.0

    @classmethod
    def _level(cls, text: str) -> int:
        value = text.casefold()
        checks = (
            (("phd", "doctor", "博士"), "phd"),
            (("master", "硕士"), "master"),
            (("bachelor", "本科", "学士"), "bachelor"),
            (("associate", "大专", "专科"), "associate"),
            (("high school", "高中"), "high_school"),
        )
        for keywords, level in checks:
            if any(keyword in value for keyword in keywords):
                return cls.levels[level]
        return 0


class ExperienceMatcher:
    years_pattern = re.compile(r"(\d+)\+?\s*(?:years?|年)", flags=re.IGNORECASE)

    def score(self, requirement: str, profile: ResumeProfile) -> float:
        required_years = self._years(requirement)
        if required_years == 0:
            return 100.0
        profile_text = " ".join(
            [profile.summary]
            + [str(item.model_dump(exclude_none=True)) for item in profile.experience]
        )
        candidate_years = self._years(profile_text)
        if candidate_years == 0 and profile.experience:
            candidate_years = len(profile.experience) * 2
        if candidate_years >= required_years:
            return 100.0
        if candidate_years == 0:
            return 0.0
        return round(max(20.0, candidate_years / required_years * 100), 2)

    def _years(self, text: str) -> int:
        matches = [int(value) for value in self.years_pattern.findall(text)]
        return max(matches, default=0)


class PreferenceScorer:
    def location_score(self, job: Job, preferences: UserPreference | None) -> float:
        if preferences is None:
            return 100.0
        location = (job.location or "").casefold()
        if not preferences.target_cities and not preferences.remote_preference:
            return 100.0
        if preferences.remote_preference and "remote" in location:
            return 100.0
        if any(city.casefold() in location for city in preferences.target_cities):
            return 100.0
        return 30.0

    def preference_score(self, job: Job, preferences: UserPreference | None) -> float:
        if preferences is None:
            return 100.0
        text = f"{job.title} {job.description}".casefold()
        criteria: list[float] = []
        if preferences.target_roles:
            criteria.append(
                100.0 if any(role.casefold() in text for role in preferences.target_roles) else 30.0
            )
        if preferences.preferred_keywords:
            coverage = sum(
                keyword.casefold() in text for keyword in preferences.preferred_keywords
            ) / len(preferences.preferred_keywords)
            criteria.append(coverage * 100)
        if preferences.preferred_companies:
            company = job.company.name.casefold() if job.company else ""
            criteria.append(
                100.0
                if company
                and any(name.casefold() == company for name in preferences.preferred_companies)
                else 50.0
            )
        if preferences.internship_type:
            criteria.append(
                100.0
                if preferences.internship_type.casefold() in (job.job_type or "").casefold()
                else 40.0
            )
        return round(sum(criteria) / len(criteria), 2) if criteria else 100.0


class LLMJudge:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.usage = UsageAccumulator()
        self.fallback_count = 0
        self.last_source = "llm"
        self.last_error: str | None = None

    async def judge(
        self,
        *,
        job: Job,
        required_skills: list[str],
        matched_skills: list[str],
        missing_skills: list[str],
        evidence: list[ResumeEvidenceRead],
        sub_scores: dict[str, float],
    ) -> LLMJudgeOutput:
        normalized = job.normalized_data or {}
        profile = StructuredJob.model_validate(normalized.get("structured_job", {}))
        prompt = build_job_judge_prompt(
            job_summary=profile.summary or job.title,
            required_skills=required_skills,
            evidence=evidence,
            sub_scores=sub_scores,
        )
        self.last_source = "llm"
        self.last_error = None
        try:
            provider_result = await self.provider.generate_structured(prompt, LLMJudgeOutput)
        except LLMProviderError as exc:
            self.last_source = "fallback"
            self.last_error = str(exc)
            self.fallback_count += 1
            logger.warning("LLM judge failed; using deterministic fallback: %s", exc)
            fallback = self._deterministic_judge(
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                evidence=evidence,
                sub_scores=sub_scores,
            )
            return fallback.model_copy(
                update={
                    "risks": [
                        *fallback.risks,
                        "LLM 服务本次未返回有效结果，已使用确定性评分降级。",
                    ]
                }
            )
        provider_usage = getattr(self.provider, "last_usage", None)
        if not isinstance(provider_usage, UsageRecord):
            provider_usage = UsageRecord(
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(provider_result.model_dump_json()),
                source="estimated",
            )
        self.usage.add(provider_usage)
        if provider_result.reasoning_summary or provider_result.strengths or provider_result.gaps:
            return provider_result
        self.last_source = "fallback"
        self.last_error = "provider returned an empty structured result"
        self.fallback_count += 1
        logger.warning("LLM judge returned an empty structured result; using fallback")
        return self._deterministic_judge(
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            evidence=evidence,
            sub_scores=sub_scores,
        )

    @staticmethod
    def _deterministic_judge(
        *,
        matched_skills: list[str],
        missing_skills: list[str],
        evidence: list[ResumeEvidenceRead],
        sub_scores: dict[str, float],
    ) -> LLMJudgeOutput:
        score = round(
            0.35 * sub_scores["semantic"]
            + 0.35 * sub_scores["skill"]
            + 0.15 * sub_scores["education"]
            + 0.15 * sub_scores["experience"],
            2,
        )
        strengths: list[str] = []
        if matched_skills:
            strengths.append("匹配技能：" + "、".join(matched_skills[:8]))
        if evidence:
            strengths.append(f"检索到 {len(evidence)} 条相关简历证据")
        gaps = ["缺少要求技能：" + "、".join(missing_skills)] if missing_skills else []
        risks: list[str] = []
        if sub_scores["experience"] < 60:
            risks.append("工作年限或经历证据不足")
        if sub_scores["semantic"] < 35:
            risks.append("简历证据与职位语义相关度偏低")
        if score >= 85:
            recommendation = "strong_apply"
        elif score >= 70:
            recommendation = "apply"
        elif score >= 50:
            recommendation = "maybe"
        else:
            recommendation = "skip"
        summary = (
            f"基于 {len(evidence)} 条检索证据，技能覆盖 {sub_scores['skill']:.0f} 分，"
            f"语义相关度 {sub_scores['semantic']:.0f} 分。"
        )
        return LLMJudgeOutput(
            score=score,
            strengths=strengths,
            gaps=gaps,
            risks=risks,
            recommendation=recommendation,
            reasoning_summary=summary,
        )


class MatchingService:
    def __init__(
        self,
        session: AsyncSession,
        provider: LLMProvider,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings or get_settings()
        self.repository = MatchingRepository(session)
        self.rag = ResumeRAG(self.repository, provider, self.settings)
        self.rules = RulesFilter()
        self.skill_coverage = SkillCoverage()
        self.education_matcher = EducationMatcher()
        self.experience_matcher = ExperienceMatcher()
        self.preference_scorer = PreferenceScorer()
        self.llm_judge = LLMJudge(provider)

    async def score(
        self,
        *,
        job_id: UUID,
        resume_id: UUID | None,
        force: bool = False,
    ) -> JobScore:
        job = await self.repository.get_job(job_id)
        if job is None:
            raise MatchingJobNotFoundError("Job not found")
        if not (job.normalized_data or {}).get("structured_job") or not job.skills:
            job = await JobService(self.session).analyze_job(job_id)
            if job is None:
                raise MatchingJobNotFoundError("Job not found")
            job = await self.repository.get_job(job_id)
            if job is None:
                raise MatchingJobNotFoundError("Job not found")

        resume = (
            await self.repository.get_resume(resume_id)
            if resume_id
            else await self.repository.get_default_resume()
        )
        if resume is None:
            raise MatchingResumeNotFoundError("Upload or select a resume before scoring")

        weights = self._normalized_weights()
        input_fingerprint = build_score_fingerprint(
            job=job,
            resume=resume,
            provider=self.provider,
            score_version=self.settings.matching_score_version,
            weights=weights,
        )
        if not force:
            cached = await self.repository.get_latest_score(
                job_id=job.id,
                resume_id=resume.id,
                score_version=self.settings.matching_score_version,
                input_fingerprint=input_fingerprint,
                judge_sources=self._cacheable_judge_sources(),
            )
            if cached is not None:
                return cached

        profile = ResumeProfile.model_validate(resume.structured_profile or {})
        preferences = await self.repository.get_preferences(resume.user_id)
        rule_result = self.rules.evaluate(job, preferences)
        evidence = await self.rag.retrieve(job, resume)
        semantic_score = self.rag.semantic_score(evidence)
        skill_result = self.skill_coverage.score(job, profile, resume_text=resume.raw_text)
        education_score = self.education_matcher.score(job.education_requirement or "", profile)
        experience_score = self.experience_matcher.score(job.experience_requirement or "", profile)
        location_score = self.preference_scorer.location_score(job, preferences)
        preference_score = self.preference_scorer.preference_score(job, preferences)

        sub_scores = {
            "semantic": semantic_score,
            "skill": skill_result.score,
            "education": education_score,
            "experience": experience_score,
            "location": location_score,
            "preference": preference_score,
        }
        required_skills = [
            skill.skill_name for skill in job.skills if skill.skill_type == "required"
        ]
        judge = await self.llm_judge.judge(
            job=job,
            required_skills=required_skills,
            matched_skills=skill_result.matched,
            missing_skills=skill_result.missing,
            evidence=evidence,
            sub_scores=sub_scores,
        )
        final_score = sum(
            weights[key] * value for key, value in {**sub_scores, "llm": judge.score}.items()
        )
        if not rule_result.passed:
            final_score = min(final_score, 25.0)
        final_score = round(final_score, 2)

        risks = list(dict.fromkeys([*judge.risks, *rule_result.reasons]))
        recommendation = "skip" if not rule_result.passed else judge.recommendation
        score = JobScore(
            job_id=job.id,
            resume_id=resume.id,
            semantic_score=semantic_score,
            skill_score=skill_result.score,
            education_score=education_score,
            experience_score=experience_score,
            location_score=location_score,
            preference_score=preference_score,
            llm_score=judge.score,
            final_score=final_score,
            rules_passed=rule_result.passed,
            rule_reasons=rule_result.reasons,
            matched_skills=skill_result.matched,
            missing_skills=skill_result.missing,
            strengths=judge.strengths,
            gaps=judge.gaps,
            risks=risks,
            resume_evidence=[item.model_dump(mode="json") for item in evidence],
            recommendation=recommendation,
            reasoning_summary=judge.reasoning_summary,
            score_version=self.settings.matching_score_version,
            input_fingerprint=input_fingerprint,
            judge_source=self.llm_judge.last_source,
            weights=weights,
        )
        return await self.repository.add_score(score)

    def _cacheable_judge_sources(self) -> tuple[str, ...]:
        # Mock scoring is deterministic and has no remote failure to recover
        # from. Remote fallback scores must be retried after the provider is
        # fixed, so they must not mask a future successful LLM result.
        if getattr(self.provider, "provider_name", None) == "mock":
            return ("llm", "fallback")
        return ("llm",)

    def _normalized_weights(self) -> dict[str, float]:
        weights = self.settings.matching_weights
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("Matching weights must have a positive total")
        return {key: value / total for key, value in weights.items()}
