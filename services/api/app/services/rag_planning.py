from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Sequence
from time import monotonic
from typing import Any

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
            candidate = await self.provider.generate_structured(
                prompt,
                RAGPlannerPlan,
                max_tokens=self.settings.rag_planner_max_tokens,
                reasoning_effort="none",
            )
            plan = self.validator.validate(candidate, fallback=fallback, filters=filters)
            if cacheable:
                _PLAN_CACHE[cache_key] = (monotonic(), plan)
                _PLAN_CACHE.move_to_end(cache_key)
                while len(_PLAN_CACHE) > _PLAN_CACHE_MAX_SIZE:
                    _PLAN_CACHE.popitem(last=False)
            return plan, _usage_snapshot(self.provider), None
        except Exception as exc:
            return (
                None,
                _usage_snapshot(self.provider),
                f"LLM 检索规划不可用，已回退规则规划：{type(exc).__name__}",
            )

    def _prompt(
        self,
        analysis: RAGQueryAnalysis,
        fallback: RAGRetrievalPlan,
        filters: JobKnowledgeFilters,
        previous_queries: Sequence[str],
        missing_information: Sequence[str],
    ) -> str:
        return (
            "你是岗位知识库检索规划器。只输出符合给定结构的 JSON，不要输出推理过程。\n"
            "任务：把用户问题拆成少量、互补、可验证的检索查询。不得改变用户筛选条件。\n"
            f"用户分析：{_compact_json(analysis.model_dump(mode='json'))}\n"
            f"规则基线：{_compact_json(fallback.model_dump(mode='json'))}\n"
            f"用户筛选：{_compact_json(filters.model_dump(mode='json'))}\n"
            f"已检索查询：{_compact_json(list(previous_queries), 1200)}\n"
            f"缺口：{_compact_json(list(missing_information), 1200)}\n"
            "要求：queries 至少 1 个且最多 6 个；查询应覆盖用户问题的不同维度；"
            "preferred_channels 只能使用 lexical/dense；hard_filters 只能原样复制用户筛选；"
            "不要生成无法从岗位知识库验证的结论。"
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
                    query=missing,
                    target_dimension=missing,
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
                "claim": item.claim,
                "text": item.evidence_text[:260],
            }
            for item in evidence[:8]
        ]
        prompt = (
            "你是证据反思器。只输出结构化 JSON，不要输出思维链。"
            "判断当前岗位知识库证据是否足以回答问题，"
            "并给出最多 4 个定向修复动作。动作必须是 expand_query/add_exact_terms/change_section/"
            "retrieve_statistics/increase_top_k/resolve_conflict。\n"
            f"问题分析：{_compact_json(analysis.model_dump(mode='json'))}\n"
            f"评估：{_compact_json(evaluation.model_dump(mode='json'))}\n"
            f"证据摘要：{_compact_json(evidence_summary)}\n"
            f"已检索：{_compact_json(list(previous_queries), 1200)}\n"
            "只诊断证据和检索策略，不编造岗位事实。"
        )
        try:
            candidate = await self.provider.generate_structured(
                prompt,
                RAGEvidenceReflection,
                max_tokens=self.settings.rag_reflection_max_tokens,
                reasoning_effort="none",
            )
            if candidate.confidence < self.settings.rag_planner_confidence_threshold:
                raise ValueError("reflection confidence is below threshold")
            if not evaluation.answerable and candidate.status == "sufficient":
                raise ValueError("reflection cannot mark an unanswerable result as sufficient")
            if not candidate.repair_actions and fallback.repair_actions:
                raise ValueError("reflection returned no actionable repair")
            return candidate, _usage_snapshot(self.provider), None
        except Exception as exc:
            return (
                fallback,
                _usage_snapshot(self.provider),
                f"LLM 证据反思不可用，已使用确定性修复：{type(exc).__name__}",
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
                "claim": item.claim,
                "text": item.evidence_text[:240],
            }
            for item in evidence[:10]
        ]
        prompt = (
            "你是回答校验器。只输出结构化 JSON，不输出思维链。"
            "检查回答中的可验证断言是否被岗位知识库证据支持，"
            "只列出确实缺少支持的断言，并选择 remove_claim、qualify_claim 或 regenerate_section。\n"
            f"回答：{answer[:6000]}\n"
            f"校验结果：{_compact_json(verification.model_dump(mode='json'))}\n"
            f"证据：{_compact_json(evidence_summary)}\n"
            "不得补写新的事实。"
        )
        try:
            candidate = await self.provider.generate_structured(
                prompt,
                RAGAnswerReflection,
                max_tokens=self.settings.rag_reflection_max_tokens,
                reasoning_effort="none",
            )
            if verification.unsupported_claims and not candidate.unsupported_claims:
                raise ValueError("answer reflection returned no unsupported claims")
            return candidate, _usage_snapshot(self.provider), None
        except Exception as exc:
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
                f"LLM 回答校验不可用，已使用确定性校验：{type(exc).__name__}",
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
