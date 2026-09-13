from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Sequence
from time import monotonic
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.schemas.knowledge_search import (
    JobKnowledgeFilters,
    RAGAnswerReflection,
    RAGEvidence,
    RAGEvidenceEvaluation,
    RAGEvidenceReflection,
    RAGPlannerPlan,
    RAGQueryAnalysis,
    RAGRepairAction,
    RAGRetrievalPlan,
    RAGRetrievalQuery,
    RAGUnsupportedClaim,
    RAGVerification,
)

_ALLOWED_CHANNELS = {"lexical", "dense"}
_ALLOWED_SECTIONS = {
    "overview",
    "requirements",
    "required_skills",
    "preferred_skills",
    "responsibilities",
    "education",
    "experience",
    "salary_benefits",
    "business_domain",
    "source_context",
    "other",
}
_PLAN_CACHE: OrderedDict[str, tuple[float, RAGRetrievalPlan]] = OrderedDict()
_PLAN_CACHE_TTL_SECONDS = 180.0
_PLAN_CACHE_MAX_SIZE = 128


class _LLMPlannerQuery(BaseModel):
    """Compact model-facing query contract."""

    query: str = Field(min_length=1, max_length=300)
    purpose: Literal[
        "semantic",
        "exact",
        "keyword",
        "aggregation",
        "comparison",
        "procedural",
    ] = "semantic"
    section_types: list[str] = Field(default_factory=list, max_length=8)
    target_dimension: str | None = Field(default=None, max_length=100)


class _LLMRetrievalPlannerDecision(BaseModel):
    """Only fields on which the LLM is allowed to decide."""

    queries: list[_LLMPlannerQuery] = Field(min_length=1, max_length=4)
    preferred_channels: list[Literal["lexical", "dense"]] = Field(
        default_factory=lambda: ["lexical", "dense"],
        max_length=2,
    )
    confidence: float = Field(default=0.0, ge=0, le=1)
    decision_summary: str = Field(default="", max_length=180)


class _LLMRepairAction(BaseModel):
    action: Literal[
        "expand_query",
        "add_exact_terms",
        "change_section",
        "retrieve_statistics",
        "increase_top_k",
        "resolve_conflict",
    ]
    query: str | None = Field(default=None, max_length=300)
    target_dimension: str | None = Field(default=None, max_length=100)
    section_types: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=160)


class _LLMEvidenceReflectionDecision(BaseModel):
    """Compact reflection contract; measured gaps remain server-owned."""

    status: Literal["sufficient", "repairable", "insufficient"] = "insufficient"
    repair_actions: list[_LLMRepairAction] = Field(default_factory=list, max_length=4)
    confidence: float = Field(default=0.0, ge=0, le=1)
    decision_summary: str = Field(default="", max_length=180)


class _LLMUnsupportedClaim(BaseModel):
    claim: str = Field(min_length=1, max_length=400)
    section: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=180)


class _LLMAnswerReflectionDecision(BaseModel):
    status: Literal["valid", "repairable", "insufficient"] = "valid"
    repair_strategy: Literal[
        "none",
        "remove_claim",
        "qualify_claim",
        "regenerate_section",
    ] = "none"
    unsupported_claims: list[_LLMUnsupportedClaim] = Field(default_factory=list, max_length=6)
    citation_gaps: list[str] = Field(default_factory=list, max_length=6)
    correction: str = Field(default="", max_length=600)
    confidence: float = Field(default=0.0, ge=0, le=1)


def clear_rag_planner_cache() -> None:
    _PLAN_CACHE.clear()


def _plan_cache_key(
    provider: LLMProvider,
    analysis: RAGQueryAnalysis,
    fallback: RAGRetrievalPlan,
    filters: JobKnowledgeFilters,
) -> str:
    payload = {
        "provider": getattr(provider, "provider_name", "unknown"),
        "model": getattr(provider, "model", "unknown"),
        "analysis": analysis.model_dump(mode="json"),
        "fallback": fallback.model_dump(mode="json"),
        "filters": filters.model_dump(mode="json"),
    }
    return hashlib.sha256(_compact_json(payload).encode("utf-8")).hexdigest()


def _usage_snapshot(provider: LLMProvider | None) -> dict[str, Any]:
    usage = getattr(provider, "last_usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        snapshot = dict(usage.model_dump())
    elif hasattr(usage, "__dict__"):
        snapshot = dict(usage.__dict__)
    else:
        return {}
    snapshot.setdefault(
        "total_tokens",
        int(snapshot.get("prompt_tokens", 0) or 0)
        + int(snapshot.get("completion_tokens", 0) or 0),
    )
    return snapshot


def _is_real_llm(provider: LLMProvider | None) -> bool:
    # Test/local adapters may expose a remote-looking provider name while still
    # being deterministic MockLLMProvider subclasses. Real providers support
    # streaming, so this also keeps the optional planner from consuming an
    # extra structured call in those adapters.
    return bool(
        provider
        and getattr(provider, "provider_name", "mock") != "mock"
        and getattr(provider, "supports_streaming", False)
        and getattr(provider, "supports_agentic_rag_planning", False)
    )


def _safe_query(value: str | None) -> str:
    return " ".join((value or "").split())[:300]


def _compact_json(value: Any, limit: int = 5000) -> str:
    rendered = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    return rendered[:limit]


def _structured_fallback_warning(
    prefix: str,
    provider: LLMProvider | None,
    token_limit: int,
) -> str:
    """Return an actionable, user-safe reason instead of an exception class."""

    usage = _usage_snapshot(provider)
    completion_tokens = int(
        usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    )
    if completion_tokens >= token_limit:
        return f"{prefix}输出达到长度上限，已使用确定性降级方案"
    return f"{prefix}暂不可用，已使用确定性降级方案"


class RetrievalPlanValidationError(ValueError):
    pass


class RetrievalPlanValidator:
    """Validates model output before it can influence retrieval."""

    _FILTER_FIELDS = (
        "cities",
        "education",
        "experience",
        "job_types",
        "platform",
        "salary_floor",
        "salary_ceiling",
        "published_after",
        "published_before",
        "job_ids",
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def validate(
        self,
        candidate: RAGPlannerPlan,
        *,
        fallback: RAGRetrievalPlan,
        filters: JobKnowledgeFilters,
    ) -> RAGRetrievalPlan:
        if candidate.confidence < self.settings.rag_planner_confidence_threshold:
            raise RetrievalPlanValidationError(
                "planner confidence is below the acceptance threshold"
            )
        if not candidate.queries:
            raise RetrievalPlanValidationError("planner returned no retrieval queries")

        queries: list[RAGRetrievalQuery] = []
        seen: set[str] = set()
        for item in candidate.queries:
            query = _safe_query(item.query)
            if not query or query.casefold() in seen:
                continue
            seen.add(query.casefold())
            sections = [section for section in item.section_types if section in _ALLOWED_SECTIONS]
            weights = {
                channel: max(0.0, min(1.0, float(weight)))
                for channel, weight in item.channel_weights.items()
                if channel in _ALLOWED_CHANNELS
            }
            queries.append(
                item.model_copy(
                    update={
                        "query": query,
                        "section_types": sections,
                        "channel_weights": weights,
                    }
                )
            )
        if not queries:
            raise RetrievalPlanValidationError("planner returned only empty retrieval queries")
        queries = queries[: self.settings.rag_max_queries]

        self._validate_hard_filters(candidate.hard_filters, filters)
        sections = sorted(
            {
                section
                for item in queries
                for section in item.section_types
                if section in _ALLOWED_SECTIONS
            }
            or set(fallback.section_types)
        )
        channels = [
            channel for channel in candidate.preferred_channels if channel in _ALLOWED_CHANNELS
        ]
        channels = list(dict.fromkeys(channels))
        if not channels:
            channels = ["lexical", "dense"]
        strategy = "full_text" if channels == ["lexical"] else "hybrid"

        return fallback.model_copy(
            update={
                "strategy": strategy,
                "vector_search": "dense" in channels,
                "keyword_search": "lexical" in channels,
                # User filters are authoritative. LLM output cannot broaden them.
                "metadata_filter": filters.model_dump(mode="json"),
                "candidate_k": min(candidate.candidate_k, self.settings.rag_fusion_top_k),
                "keyword_top_k": min(candidate.keyword_top_k, self.settings.rag_keyword_top_k),
                "vector_top_k": min(candidate.vector_top_k, self.settings.rag_vector_top_k),
                "rerank_k": min(candidate.rerank_k, self.settings.rag_rerank_top_k),
                "max_iterations": min(candidate.max_iterations, fallback.max_iterations),
                "section_types": sections,
                "planned_queries": queries,
                "planner_source": "llm",
                "planner_confidence": candidate.confidence,
                "plan_version": "llm-v1",
                "preferred_channels": channels,
                "expected_evidence": candidate.expected_evidence[:20],
                "hard_filters": filters,
                "soft_filters": candidate.soft_filters,
            }
        )

    def _validate_hard_filters(
        self,
        requested: JobKnowledgeFilters,
        actual: JobKnowledgeFilters,
    ) -> None:
        for field in self._FILTER_FIELDS:
            proposed = getattr(requested, field)
            if proposed in (None, [], ""):
                continue
            if proposed != getattr(actual, field):
                raise RetrievalPlanValidationError(
                    f"planner attempted to change user filter: {field}"
                )


class LLMRetrievalPlanner:
    """Optional semantic planner. Rules remain the executable fallback."""

    def __init__(self, provider: LLMProvider | None, settings: Settings | None = None) -> None:
        self.provider = provider
        self.settings = settings or get_settings()
        self.validator = RetrievalPlanValidator(self.settings)

    def should_use(self, analysis: RAGQueryAnalysis) -> bool:
        return bool(
            self.settings.rag_llm_planner_enabled
            and _is_real_llm(self.provider)
            and (
                analysis.complexity != "simple"
                or analysis.question_type
                in {"aggregation", "comparison", "procedural", "multi_hop"}
            )
        )

    async def plan(
        self,
        analysis: RAGQueryAnalysis,
        fallback: RAGRetrievalPlan,
        filters: JobKnowledgeFilters,
        *,
        previous_queries: Sequence[str] = (),
        missing_information: Sequence[str] = (),
    ) -> tuple[RAGRetrievalPlan | None, dict[str, Any], str | None]:
        if not self.should_use(analysis) or self.provider is None:
            return None, {}, None
        cacheable = not previous_queries and not missing_information
        cache_key = _plan_cache_key(self.provider, analysis, fallback, filters)
        cached = _PLAN_CACHE.get(cache_key) if cacheable else None
        if cached is not None:
            cached_at, cached_plan = cached
            if monotonic() - cached_at <= _PLAN_CACHE_TTL_SECONDS:
                _PLAN_CACHE.move_to_end(cache_key)
                return (
                    cached_plan.model_copy(update={"planner_source": "llm_cache"}),
                    {},
                    None,
                )
            _PLAN_CACHE.pop(cache_key, None)
        prompt = self._prompt(analysis, fallback, filters, previous_queries, missing_information)
        try:
            decision = await self.provider.generate_structured(
                prompt,
                _LLMRetrievalPlannerDecision,
                max_tokens=self.settings.rag_planner_max_tokens,
                reasoning_effort="none",
            )
            candidate = RAGPlannerPlan(
                normalized_question=analysis.original_query,
                question_type=analysis.question_type,
                complexity=analysis.complexity,
                answer_dimensions=analysis.required_information,
                queries=[
                    RAGRetrievalQuery(
                        query=item.query,
                        purpose=item.purpose,
                        section_types=item.section_types,
                        target_dimension=item.target_dimension,
                    )
                    for item in decision.queries
                ],
                hard_filters=filters,
                preferred_channels=decision.preferred_channels,
                expected_evidence=analysis.required_information,
                keyword_top_k=fallback.keyword_top_k,
                vector_top_k=fallback.vector_top_k,
                candidate_k=fallback.candidate_k,
                rerank_k=fallback.rerank_k,
                max_iterations=fallback.max_iterations,
                confidence=decision.confidence,
                decision_summary=decision.decision_summary,
            )
            plan = self.validator.validate(candidate, fallback=fallback, filters=filters)
            if cacheable:
                _PLAN_CACHE[cache_key] = (monotonic(), plan)
                _PLAN_CACHE.move_to_end(cache_key)
                while len(_PLAN_CACHE) > _PLAN_CACHE_MAX_SIZE:
                    _PLAN_CACHE.popitem(last=False)
            return plan, _usage_snapshot(self.provider), None
        except Exception:
            return (
                None,
                _usage_snapshot(self.provider),
                _structured_fallback_warning(
                    "LLM 检索规划",
                    self.provider,
                    self.settings.rag_planner_max_tokens,
                ).replace("确定性降级方案", "规则规划"),
            )

    def _prompt(
        self,
        analysis: RAGQueryAnalysis,
        fallback: RAGRetrievalPlan,
        filters: JobKnowledgeFilters,
        previous_queries: Sequence[str],
        missing_information: Sequence[str],
    ) -> str:
        analysis_payload = {
            "question": analysis.original_query,
            "type": analysis.question_type,
            "complexity": analysis.complexity,
            "entities": analysis.entities,
            "required": analysis.required_information,
        }
        baseline_payload = {
            "strategy": fallback.strategy,
            "sections": fallback.section_types,
            "max_queries": min(4, self.settings.rag_max_queries),
        }
        filter_payload = filters.model_dump(
            mode="json",
            exclude_none=True,
            exclude_defaults=True,
        )
        return (
            "你是岗位知识库检索规划器，只返回简短 JSON。"
            "生成 1 至 4 个互补查询，优先覆盖 required/缺口；不输出事实、解释或筛选条件。\n"
            f"分析：{_compact_json(analysis_payload, 1800)}\n"
            f"基线：{_compact_json(baseline_payload, 1200)}\n"
            f"只读筛选：{_compact_json(filter_payload, 1000)}\n"
            f"已检索：{_compact_json(list(previous_queries), 600)}\n"
            f"缺口：{_compact_json(list(missing_information), 600)}\n"
            "section_types 仅从基线 sections 选择；channel 仅 lexical/dense；"
            "decision_summary 一句话且不超过 60 字。"
        )


class EvidenceReflectionService:
    """Combines deterministic checks with optional LLM diagnosis."""

    def __init__(self, provider: LLMProvider | None, settings: Settings | None = None) -> None:
        self.provider = provider
        self.settings = settings or get_settings()

    def deterministic(
        self,
        evaluation: RAGEvidenceEvaluation,
        *,
        iteration: int,
        max_iterations: int,
    ) -> RAGEvidenceReflection:
        failure_types: list[str] = []
        if not evaluation.missing_information:
            if evaluation.max_relevance_score < self.settings.rag_evidence_min_relevance:
                failure_types.append("low_precision")
            elif not evaluation.answerable:
                failure_types.append("low_recall")
        else:
            failure_types.append("coverage_gap")
        if evaluation.conflicts:
            failure_types.append("conflicting_evidence")

        actions: list[RAGRepairAction] = []
        for missing in evaluation.missing_information[:4]:
            action_name = "retrieve_statistics" if any(
                token in missing
                for token in (
                    "薪资",
                    "salary",
                    "学历分布",
                    "education",
                    "经验分布",
                    "experience",
                    "比例",
                    "distribution",
                )
            ) else "change_section"
            actions.append(
                RAGRepairAction(
                    action=action_name,
                    query=(
                        f"{missing} 岗位职责 工作内容"
                        if missing == "responsibilities"
                        else missing
                    ),
                    target_dimension=missing,
                    section_types=(
                        ["responsibilities", "requirements", "source_context"]
                        if missing == "responsibilities"
                        else []
                    ),
                    reason="补齐证据覆盖缺口",
                )
            )
        if not actions and "low_recall" in failure_types:
            actions.append(RAGRepairAction(action="expand_query", reason="扩大召回范围"))
        if not actions and evaluation.conflicts:
            actions.append(RAGRepairAction(action="resolve_conflict", reason="重新检索冲突来源"))

        repairable = bool(iteration < max_iterations - 1 and actions)
        return RAGEvidenceReflection(
            status="repairable" if repairable else "insufficient",
            failure_types=list(dict.fromkeys(failure_types)),
            missing_information=evaluation.missing_information[:20],
            repair_actions=actions[:8],
            confidence=0.85,
            decision_summary=(
                "证据存在覆盖缺口，执行一次定向修复"
                if repairable
                else "证据不足且已达到修复上限"
            ),
        )

    async def reflect(
        self,
        analysis: RAGQueryAnalysis,
        evaluation: RAGEvidenceEvaluation,
        evidence: Sequence[RAGEvidence],
        *,
        iteration: int,
        max_iterations: int,
        previous_queries: Sequence[str] = (),
    ) -> tuple[RAGEvidenceReflection, dict[str, Any], str | None]:
        fallback = self.deterministic(
            evaluation, iteration=iteration, max_iterations=max_iterations
        )
        if not self.settings.rag_reflection_enabled or not _is_real_llm(self.provider):
            return fallback, {}, None
        evidence_summary = [
            {
                "topic": item.topic,
                "claim": item.claim[:180],
            }
            for item in evidence[:6]
        ]
        analysis_payload = {
            "question": analysis.original_query,
            "type": analysis.question_type,
            "required": analysis.required_information,
        }
        evaluation_payload = {
            "answerable": evaluation.answerable,
            "coverage": evaluation.coverage_score,
            "max_relevance": evaluation.max_relevance_score,
            "missing": evaluation.missing_information,
            "conflicts": evaluation.conflicts,
        }
        prompt = (
            "你是证据检索修复器，只返回简短 JSON，不输出思维链或岗位事实。"
            "以评估中的 missing 为准，给出最多 4 个可执行修复动作；"
            "有缺口时不得返回 sufficient。\n"
            f"分析：{_compact_json(analysis_payload, 1600)}\n"
            f"评估：{_compact_json(evaluation_payload, 1600)}\n"
            f"证据主题：{_compact_json(evidence_summary, 1800)}\n"
            f"已检索：{_compact_json(list(previous_queries), 600)}\n"
            "动作限 expand_query/add_exact_terms/change_section/retrieve_statistics/"
            "increase_top_k/resolve_conflict；summary 不超过 60 字。"
        )
        try:
            decision = await self.provider.generate_structured(
                prompt,
                _LLMEvidenceReflectionDecision,
                max_tokens=self.settings.rag_reflection_max_tokens,
                reasoning_effort="none",
            )
            candidate = RAGEvidenceReflection(
                status=decision.status,
                failure_types=fallback.failure_types,
                missing_information=evaluation.missing_information,
                repair_actions=[
                    RAGRepairAction(
                        action=item.action,
                        query=item.query,
                        target_dimension=item.target_dimension,
                        section_types=item.section_types,
                        reason=item.reason,
                    )
                    for item in decision.repair_actions
                ],
                confidence=decision.confidence,
                decision_summary=decision.decision_summary,
            )
            if candidate.confidence < self.settings.rag_planner_confidence_threshold:
                raise ValueError("reflection confidence is below threshold")
            if not evaluation.answerable and candidate.status == "sufficient":
                raise ValueError("reflection cannot mark an unanswerable result as sufficient")
            if not candidate.repair_actions and fallback.repair_actions:
                raise ValueError("reflection returned no actionable repair")
            return candidate, _usage_snapshot(self.provider), None
        except Exception:
            return (
                fallback,
                _usage_snapshot(self.provider),
                _structured_fallback_warning(
                    "LLM 证据反思",
                    self.provider,
                    self.settings.rag_reflection_max_tokens,
                ).replace("确定性降级方案", "确定性修复"),
            )


class AnswerReflectionService:
    """Verifies answer claims and creates a transparent, append-only repair note."""

    def __init__(self, provider: LLMProvider | None, settings: Settings | None = None) -> None:
        self.provider = provider
        self.settings = settings or get_settings()

    async def reflect(
        self,
        answer: str,
        verification: RAGVerification,
        evidence: Sequence[RAGEvidence],
    ) -> tuple[RAGAnswerReflection, dict[str, Any], str | None]:
        if not self.settings.rag_answer_reflection_enabled or not _is_real_llm(self.provider):
            return RAGAnswerReflection(), {}, None
        if not verification.unsupported_claims and verification.groundedness == "supported":
            return RAGAnswerReflection(status="valid", confidence=0.95), {}, None
        evidence_summary = [
            {
                "topic": item.topic,
                "claim": item.claim[:220],
            }
            for item in evidence[:8]
        ]
        prompt = (
            "你是回答证据校验器，只返回简短 JSON，不输出思维链。"
            "仅复核待核实断言；证据足以支持时不要列为 unsupported。"
            "不得补写事实，correction 最多两句话。\n"
            f"待核实断言：{_compact_json(verification.unsupported_claims[:8], 1800)}\n"
            f"回答摘要：{answer[:2800]}\n"
            f"证据断言：{_compact_json(evidence_summary, 2600)}\n"
            "repair_strategy 仅 none/remove_claim/qualify_claim/regenerate_section。"
        )
        try:
            decision = await self.provider.generate_structured(
                prompt,
                _LLMAnswerReflectionDecision,
                max_tokens=self.settings.rag_reflection_max_tokens,
                reasoning_effort="none",
            )
            candidate = RAGAnswerReflection(
                status=decision.status,
                repair_strategy=decision.repair_strategy,
                unsupported_claims=[
                    RAGUnsupportedClaim(
                        claim=item.claim,
                        section=item.section,
                        reason=item.reason,
                    )
                    for item in decision.unsupported_claims
                ],
                citation_gaps=decision.citation_gaps,
                correction=decision.correction,
                confidence=decision.confidence,
            )
            if candidate.status == "repairable" and not candidate.unsupported_claims:
                raise ValueError("repairable answer reflection returned no actionable claims")
            return candidate, _usage_snapshot(self.provider), None
        except Exception:
            claims = [
                RAGUnsupportedClaim(claim=claim, reason="回答校验未找到对应证据")
                for claim in verification.unsupported_claims[:8]
            ]
            return (
                RAGAnswerReflection(
                    status="repairable" if claims else "insufficient",
                    repair_strategy="qualify_claim" if claims else "none",
                    unsupported_claims=claims,
                    confidence=0.8,
                ),
                _usage_snapshot(self.provider),
                _structured_fallback_warning(
                    "LLM 回答校验",
                    self.provider,
                    self.settings.rag_reflection_max_tokens,
                ).replace("确定性降级方案", "确定性校验"),
            )

    def local_repair(self, reflection: RAGAnswerReflection) -> str:
        if not reflection.unsupported_claims:
            return ""
        claims = "\n".join(
            f"- {item.claim}（{item.reason or '缺少直接岗位证据'}）"
            for item in reflection.unsupported_claims[:8]
            if item.claim.strip()
        )
        if not claims:
            return ""
        return (
            "\n\n## 回答校验修正\n\n"
            "以下内容未在当前知识库证据中得到充分支持，已降级为待核实信息，请勿将其视为确定结论：\n"
            f"{claims}"
        )
