from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job, JobScore, RequirementMatch, Resume, UserPreference
from app.repositories.matching import MatchingRepository
from app.schemas.matching import QuickScoreBatchResponse, QuickScoreRead, Recommendation
from app.schemas.resumes import ResumeProfile
from app.services.matching import PreferenceScorer, RulesFilter
from app.services.requirement_matching import (
    JOB_REQUIREMENT_VERSION,
    RequirementEvaluation,
    evaluate_requirements,
    sync_job_requirements,
)


class QuickMatchingJobNotFoundError(ValueError):
    """Raised when a requested quick-score job does not exist."""


class QuickMatchingResumeNotFoundError(ValueError):
    """Raised when no requested or default resume exists."""


class QuickMatchingService:
    """Evidence-first deterministic scoring for incremental job discovery."""

    SCORE_VERSION = "QUICK_MATCH_V3_3"
    WEIGHTS = {
        "direction": 0.20,
        "must_have": 0.45,
        "preferred": 0.10,
        "experience": 0.15,
        "education": 0.10,
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = MatchingRepository(session)
        self.rules = RulesFilter()
        self.preference_scorer = PreferenceScorer()

    async def score_many(
        self, *, job_ids: list[UUID], resume_id: UUID | None
    ) -> QuickScoreBatchResponse:
        requested_ids = list(dict.fromkeys(job_ids))
        jobs = await self.repository.get_jobs(requested_ids)
        jobs_by_id = {job.id: job for job in jobs}
        if any(job_id not in jobs_by_id for job_id in requested_ids):
            raise QuickMatchingJobNotFoundError("One or more jobs do not exist")
        resume = (
            await self.repository.get_resume(resume_id)
            if resume_id
            else await self.repository.get_default_resume()
        )
        if resume is None:
            raise QuickMatchingResumeNotFoundError("Upload or select a resume before quick scoring")
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
            requirements = [
                item for item in job.requirements if item.parser_version == JOB_REQUIREMENT_VERSION
            ]
            if not requirements:
                requirements = await sync_job_requirements(self.session, job)
            score = self._build_score(job, resume, preferences, fingerprint, requirements)
            new_scores.append(score)
            results.append(self._read(score, cached=False))
        if new_scores:
            self.session.add_all(new_scores)
            await self.session.commit()
        return QuickScoreBatchResponse(items=results)

    def _build_score(
        self,
        job: Job,
        resume: Resume,
        preferences: UserPreference | None,
        fingerprint: str,
        requirements,
    ) -> JobScore:
        profile = ResumeProfile.model_validate(resume.structured_profile or {})
        rule_result = self.rules.evaluate(job, preferences)
        evaluations = evaluate_requirements(requirements, resume, profile)
        grouped = {
            kind: [item for item in evaluations if item.requirement.requirement_type == kind]
            for kind in (
                "direction",
                "must_have_skill",
                "preferred_skill",
                "experience",
                "education",
            )
        }
        context_skills = [
            item
            for item in evaluations
            if item.requirement.requirement_type == "context_skill"
        ]
        components = {
            "direction": self._aggregate(grouped["direction"], unknown=50.0),
            "must_have": self._aggregate_required_evidence(grouped["must_have_skill"]),
            "preferred": self._aggregate(grouped["preferred_skill"], unknown=50.0),
            "experience": self._aggregate(grouped["experience"], unknown=55.0),
            "education": self._aggregate(grouped["education"], unknown=55.0),
        }
        # Hard failures are represented once in the ledger/cap layer. Their raw
        # component scores remain available for explanation, but are not applied
        # a second time to the weighted base score.
        base_components = dict(components)
        if any(item.status == "missing" for item in grouped["direction"]):
            base_components["direction"] = 100.0
        if any(
            item.status == "missing" and item.requirement.is_hard
            for item in grouped["education"]
        ):
            base_components["education"] = 100.0
        if any(item.status == "missing" and item.hard_constraint for item in grouped["experience"]):
            base_components["experience"] = 100.0
        base_score = sum(self.WEIGHTS[key] * value for key, value in base_components.items())
        missing_must = [item for item in grouped["must_have_skill"] if item.status == "missing"]
        deduction = sum(item.deduction for item in missing_must)
        final_score = base_score - deduction
        hard_reasons: list[str] = []
        hard_ledger: list[dict[str, object]] = []

        for item in missing_must:
            metadata = item.requirement.requirement_metadata or {}
            if item.requirement.is_critical:
                hard_ledger.append(
                    {
                        "requirement_group_id": metadata.get("group_id")
                        or str(item.requirement.id),
                        "reason": "critical_skill_missing",
                        "penalty": 0.0,
                        "cap": 50.0,
                        "affected_requirements": metadata.get("group_members")
                        or [item.requirement.normalized_value],
                        "source_text": item.requirement.source_text,
                    }
                )
            elif item.deduction:
                hard_ledger.append(
                    {
                        "requirement_group_id": metadata.get("group_id")
                        or str(item.requirement.id),
                        "reason": "must_have_skill_missing",
                        "penalty": item.deduction,
                        "cap": None,
                        "affected_requirements": metadata.get("group_members")
                        or [item.requirement.normalized_value],
                        "source_text": item.requirement.source_text,
                    }
                )

        direction = grouped["direction"][0] if grouped["direction"] else None
        if direction and direction.status == "missing":
            final_score = min(final_score, 35.0)
            hard_reasons.append("岗位职能方向与简历主方向不一致（封顶 35 分）")
            hard_ledger.append(self._cap_entry(direction, "direction_mismatch", 35.0))
        elif direction and direction.status == "unknown":
            pass
        if any(item.requirement.is_critical for item in missing_must):
            final_score = min(final_score, 50.0)
            hard_reasons.append("缺少关键必备技能（封顶 50 分）")
        missing_education = next(
            (
                item
                for item in grouped["education"]
                if item.status == "missing" and item.requirement.is_hard
            ),
            None,
        )
        if missing_education:
            final_score = min(final_score, 40.0)
            hard_reasons.append("学历未达到岗位硬性要求（封顶 40 分）")
            hard_ledger.append(self._cap_entry(missing_education, "education_missing", 40.0))
        missing_experience = next(
            (
                item
                for item in grouped["experience"]
                if item.status == "missing" and item.hard_constraint
            ),
            None,
        )
        if missing_experience:
            final_score = min(final_score, 55.0)
            hard_reasons.append("经验差距超过允许阈值（封顶 55 分）")
            hard_ledger.append(self._cap_entry(missing_experience, "experience_gap", 55.0))
        if not rule_result.passed:
            final_score = min(final_score, 25.0)
        final_score = round(max(0.0, min(100.0, final_score)), 2)

        hard_passed = not hard_reasons
        matched = [
            item.requirement.normalized_value
            for item in evaluations
            if item.requirement.requirement_type.endswith("skill") and item.status == "matched"
        ]
        missing = [item.requirement.normalized_value for item in missing_must]
        score_status, confidence_factors, confidence = self._score_reliability(
            job, evaluations, context_skills
        )
        reasons = [*rule_result.reasons, *hard_reasons]
        direction_text = components["direction"]
        must_text = components["must_have"]
        preferred_text = components["preferred"]
        experience_text = components["experience"]
        education_text = components["education"]
        reasoning = (
            f"快速评分 V3（不调用 LLM）：方向 {direction_text:.0f}，"
            f"必备技能 {must_text:.0f}，加分技能 {preferred_text:.0f}，"
            f"经验 {experience_text:.0f}，学历 {education_text:.0f}。"
            + (f"缺失必备技能扣 {deduction:.0f} 分。" if deduction else "")
            + ("；".join(hard_reasons) if hard_reasons else "")
            + (
                "职位描述信息不足，当前结果仅供参考。"
                if score_status != "SUFFICIENT"
                else ""
            )
        )
        score = JobScore(
            job_id=job.id,
            resume_id=resume.id,
            semantic_score=components["direction"],
            skill_score=round(components["must_have"] * 0.82 + components["preferred"] * 0.18, 2),
            education_score=components["education"],
            experience_score=components["experience"],
            location_score=self.preference_scorer.location_score(job, preferences),
            preference_score=self.preference_scorer.preference_score(job, preferences),
            llm_score=0.0,
            final_score=final_score,
            rules_passed=rule_result.passed and hard_passed,
            rule_reasons=reasons,
            matched_skills=matched,
            missing_skills=missing,
            strengths=["有明确简历证据：" + "、".join(matched[:8])] if matched else [],
            gaps=["缺少必备技能：" + "、".join(missing)] if missing else [],
            risks=reasons,
            # Atomic evidence is stored in RequirementMatch. Keep this legacy
            # field reserved for embedding-backed ResumeEvidenceRead records.
            resume_evidence=[],
            recommendation=self._recommendation(final_score),
            reasoning_summary=reasoning,
            score_version=self.SCORE_VERSION,
            input_fingerprint=fingerprint,
            judge_source="deterministic",
            weights=self.WEIGHTS,
            direction_score=components["direction"],
            score_confidence=confidence,
            score_status=score_status,
            confidence_factors=confidence_factors,
            hard_constraint_ledger=hard_ledger,
            hard_constraint_passed=hard_passed,
        )
        score.requirement_matches = [self._match_entity(item) for item in evaluations]
        return score

    @staticmethod
    def _match_entity(item: RequirementEvaluation) -> RequirementMatch:
        return RequirementMatch(
            job_requirement_id=item.requirement.id,
            requirement_type=item.requirement.requirement_type,
            requirement_value=item.requirement.normalized_value,
            status=item.status,
            score=item.score,
            evidence=item.evidence,
            match_method=item.match_method,
            confidence=item.confidence,
            deduction=item.deduction,
            hard_constraint=item.hard_constraint,
        )

    @staticmethod
    def _aggregate(items: list[RequirementEvaluation], *, unknown: float) -> float:
        if not items:
            return unknown
        weights = [
            max(0.1, item.requirement.importance * item.requirement.specificity) for item in items
        ]
        return round(
            sum(item.score * weight for item, weight in zip(items, weights, strict=True))
            / sum(weights),
            2,
        )

    @staticmethod
    def _aggregate_required_evidence(items: list[RequirementEvaluation]) -> float:
        if not items:
            return 45.0
        matched = [item for item in items if item.status == "matched"]
        if not matched:
            return 0.0
        weights = [
            max(0.1, item.requirement.importance * item.requirement.specificity)
            for item in matched
        ]
        return round(
            sum(item.score * weight for item, weight in zip(matched, weights, strict=True))
            / sum(weights),
            2,
        )

    @staticmethod
    def _cap_entry(
        item: RequirementEvaluation, reason: str, cap: float
    ) -> dict[str, object]:
        metadata = item.requirement.requirement_metadata or {}
        return {
            "requirement_group_id": metadata.get("group_id") or str(item.requirement.id),
            "reason": reason,
            "penalty": 0.0,
            "cap": cap,
            "affected_requirements": [item.requirement.normalized_value],
            "source_text": item.requirement.source_text,
        }

    @staticmethod
    def _score_reliability(
        job: Job,
        evaluations: list[RequirementEvaluation],
        context_skills: list[RequirementEvaluation],
    ) -> tuple[str, dict[str, float], float]:
        substantive = [
            item
            for item in evaluations
            if item.requirement.requirement_type
            in {"must_have_skill", "preferred_skill", "education", "experience"}
        ]
        description_length = len((job.description or "").strip())
        if not substantive or description_length < 40:
            status = "INSUFFICIENT_DATA"
        elif description_length < 120 or not any(
            item.requirement.requirement_type == "must_have_skill" for item in substantive
        ):
            status = "PARTIAL"
        else:
            status = "SUFFICIENT"
        jd_completeness = min(1.0, description_length / 500.0)
        extraction = (
            sum(item.requirement.extraction_confidence for item in evaluations) / len(evaluations)
            if evaluations
            else 0.0
        )
        logic = (
            sum(
                0.95
                if (item.requirement.requirement_metadata or {}).get("group_operator")
                else 0.65
                for item in substantive
            )
            / len(substantive)
            if substantive
            else 0.0
        )
        skill_items = [
            item for item in substantive if item.requirement.requirement_type.endswith("skill")
        ]
        evidence_coverage = (
            sum(item.status in {"matched", "not_required"} for item in skill_items)
            / len(skill_items)
            if skill_items
            else 0.0
        )
        unknown_ratio = (
            sum(item.status == "unknown" for item in evaluations) / len(evaluations)
            if evaluations
            else 1.0
        )
        factors = {
            "jd_completeness": round(jd_completeness, 3),
            "requirement_extraction": round(extraction, 3),
            "logical_grouping": round(logic, 3),
            "resume_evidence_coverage": round(evidence_coverage, 3),
            "unknown_ratio": round(unknown_ratio, 3),
            "context_requirement_ratio": round(
                len(context_skills) / max(1, len(evaluations)), 3
            ),
        }
        confidence = (
            0.25 * jd_completeness
            + 0.25 * extraction
            + 0.2 * logic
            + 0.2 * evidence_coverage
            + 0.1 * (1.0 - unknown_ratio)
        )
        if status == "PARTIAL":
            confidence = min(confidence, 0.74)
        elif status == "INSUFFICIENT_DATA":
            confidence = min(confidence, 0.35)
        return status, factors, round(max(0.0, min(1.0, confidence)), 3)

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
    def _fingerprint(cls, job: Job, resume: Resume, preferences: UserPreference | None) -> str:
        payload = {
            "version": cls.SCORE_VERSION,
            "requirements": JOB_REQUIREMENT_VERSION,
            "job_id": str(job.id),
            "job_content_hash": job.content_hash,
            "job_updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "resume_id": str(resume.id),
            "resume_version": resume.version,
            "resume_updated_at": resume.updated_at.isoformat() if resume.updated_at else None,
            "preference": {
                "target_roles": preferences.target_roles if preferences else [],
                "target_cities": preferences.target_cities if preferences else [],
                "required_keywords": preferences.required_keywords if preferences else [],
                "excluded_keywords": preferences.excluded_keywords if preferences else [],
                "blocked_companies": preferences.blocked_companies if preferences else [],
            },
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _read(score: JobScore, *, cached: bool) -> QuickScoreRead:
        matches = [
            {
                "requirement_type": item.requirement_type,
                "requirement_value": item.requirement_value,
                "status": item.status,
                "score": item.score,
                "evidence": item.evidence,
                "match_method": item.match_method,
                "confidence": item.confidence,
                "deduction": item.deduction,
                "hard_constraint": item.hard_constraint,
            }
            for item in score.requirement_matches
        ]
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
            direction_score=score.direction_score,
            score_confidence=score.score_confidence,
            score_status=score.score_status,
            confidence_factors=score.confidence_factors,
            hard_constraint_ledger=score.hard_constraint_ledger,
            hard_constraint_passed=score.hard_constraint_passed,
            component_scores={
                "direction": score.direction_score,
                "skill": score.skill_score,
                "education": score.education_score,
                "experience": score.experience_score,
            },
            requirement_matches=matches,
            cached=cached,
        )
