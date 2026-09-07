from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections import OrderedDict, defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID, uuid4

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.llm.usage import estimate_tokens
from app.schemas.knowledge_search import (
    AgenticRAGSearchResponse,
    JobKnowledgeCitation,
    JobKnowledgeFilters,
    JobKnowledgeSearchRequest,
    JobKnowledgeSearchResponse,
    RAGAnswerReflection,
    RAGEvidence,
    RAGEvidenceEvaluation,
    RAGEvidenceReflection,
    RAGEvidenceSource,
    RAGQueryAnalysis,
    RAGQueryRewrite,
    RAGRetrievalPlan,
    RAGTrace,
    RAGVerification,
)
from app.services.job_knowledge import SKILL_ALIASES, canonicalize_skill
from app.services.job_knowledge_rag import (
    JobKnowledgeRAG,
    KnowledgeEmbeddingUnavailableError,
    KnowledgeRetrievalError,
    extract_query_terms,
)
from app.services.rag_planning import (
    AnswerReflectionService,
    EvidenceReflectionService,
    LLMRetrievalPlanner,
)

RAGStatusCallback = Callable[[str, dict], Awaitable[None]]

_ANALYSIS_CACHE: OrderedDict[str, tuple[float, RAGQueryAnalysis]] = OrderedDict()
_ANALYSIS_CACHE_TTL_SECONDS = 300.0
_ANALYSIS_CACHE_MAX_SIZE = 256
_SECTION_RERANK_WEIGHTS = {
    "requirements": 1.0,
    "required_skills": 0.98,
    "responsibilities": 0.96,
    "education": 0.88,
    "experience": 0.88,
    "salary_benefits": 0.86,
    "preferred_skills": 0.78,
    "overview": 0.72,
    "business_domain": 0.68,
    "source_context": 0.5,
    "other": 0.55,
}
_INFORMATION_SECTIONS = {
    "overview": set(_SECTION_RERANK_WEIGHTS),
    "skills": {
        "requirements",
        "required_skills",
        "preferred_skills",
        "responsibilities",
        "source_context",
    },
    "responsibilities": {"responsibilities", "requirements", "source_context"},
    "education": {"education", "requirements", "source_context"},
    "experience": {"experience", "requirements", "source_context"},
    "salary": {"salary_benefits", "source_context"},
    "learning_path": {
        "requirements",
        "required_skills",
        "responsibilities",
        "source_context",
    },
    "comparison_dimensions": {
        "overview",
        "requirements",
        "responsibilities",
        "source_context",
    },
}
_INFORMATION_QUERY_LABELS = {
    "overview": "岗位概览",
    "skills": "必备技能 任职要求",
    "responsibilities": "岗位职责 工作内容",
    "education": "学历要求",
    "experience": "经验要求",
    "salary": "薪资待遇",
    "learning_path": "技能要求 项目经验",
    "comparison_dimensions": "岗位职责 任职要求 对比",
}
_ROLE_SUFFIX_PATTERN = re.compile(
    r"([A-Za-z0-9+#./\u3400-\u9fff ]{2,48}?"
    r"(?:实习生|工程师|产品经理|研究员|分析师|设计师|开发岗|算法岗))",
    flags=re.I,
)
_ROLE_PREFIX_CUES = (
    "分析",
    "了解",
    "查询",
    "关于",
    "应聘",
    "成为",
    "学习",
    "转行",
)
_GENERIC_ROLE_TERMS = {
    "岗位",
    "职位",
    "实习",
    "实习生",
    "工程师",
    "开发",
    "算法",
    "要求",
    "技能",
}


def clear_agentic_rag_cache() -> None:
    _ANALYSIS_CACHE.clear()


def _compact(value: str, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]


def _tokens(value: str) -> set[str]:
    normalized = value.casefold()
    tokens = {item for item in re.findall(r"[a-z0-9][a-z0-9+#._/-]*", normalized) if len(item) > 1}
    for segment in re.findall(r"[\u3400-\u9fff]+", normalized):
        tokens.update(segment[index : index + 2] for index in range(len(segment) - 1))
    return tokens


def _overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens))


def _merge_similar_queries(queries: Sequence[str], limit: int) -> list[str]:
    """Collapse near-duplicate rewrites before retrieval and embedding."""

    groups: list[tuple[str, set[str]]] = []
    for raw_query in queries:
        query = _compact(raw_query, 300)
        if not query:
            continue
        terms = set(extract_query_terms(query)) or _tokens(query)
        match_index = next(
            (
                index
                for index, (_, group_terms) in enumerate(groups)
                if terms
                and group_terms
                and len(terms & group_terms) / max(1, min(len(terms), len(group_terms))) >= 0.7
            ),
            None,
        )
        if match_index is None:
            groups.append((query, terms))
            continue
        previous, group_terms = groups[match_index]
        if query.casefold() not in previous.casefold():
            groups[match_index] = (_compact(f"{previous}；{query}", 300), group_terms | terms)
    return [query for query, _ in groups[:limit]]


def _normalized_claim(value: str) -> str:
    normalized = re.sub(r"[#*_`>\-•·]+", " ", value.casefold())
    return re.sub(r"[^a-z0-9\u3400-\u9fff+#.]+", "", normalized)


def _claim_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw in value.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}|[-*•·]|\d+[.)、])\s*", "", raw).strip()
        if len(line) >= 4:
            lines.extend(
                item.strip()
                for item in re.split(r"(?<=[。！？；])", line)
                if len(item.strip()) >= 4
            )
    return list(dict.fromkeys(lines))


def _analysis_cache_key(query: str, intent: str) -> str:
    return hashlib.sha256(f"{intent}:{_compact(query, 800).casefold()}".encode()).hexdigest()


def _extract_role_entities(query: str) -> list[str]:
    roles: list[str] = []
    for match in _ROLE_SUFFIX_PATTERN.finditer(query):
        value = _compact(match.group(1), 60).strip(" ，。！？?:：")
        for cue in _ROLE_PREFIX_CUES:
            if cue in value:
                value = value.rsplit(cue, 1)[-1].strip()
        value = re.sub(r"^(?:请|帮我|我想|现有|目标)", "", value).strip()
        if 3 <= len(value) <= 40 and value not in _GENERIC_ROLE_TERMS:
            roles.append(value)
    return list(dict.fromkeys(roles))[:3]


def _cache_analysis(key: str, analysis: RAGQueryAnalysis) -> None:
    _ANALYSIS_CACHE[key] = (time.monotonic(), analysis)
    _ANALYSIS_CACHE.move_to_end(key)
    while len(_ANALYSIS_CACHE) > _ANALYSIS_CACHE_MAX_SIZE:
        _ANALYSIS_CACHE.popitem(last=False)


def _cached_analysis(key: str) -> RAGQueryAnalysis | None:
    cached = _ANALYSIS_CACHE.get(key)
    if cached is None:
        return None
    created_at, analysis = cached
    if time.monotonic() - created_at > _ANALYSIS_CACHE_TTL_SECONDS:
        _ANALYSIS_CACHE.pop(key, None)
        return None
    _ANALYSIS_CACHE.move_to_end(key)
    return analysis


class QueryAnalyzer:
    """Produce structured retrieval decisions without exposing model reasoning."""

    def analyze(
        self,
        query: str,
        *,
        intent: str = "knowledge_query",
        filters: JobKnowledgeFilters | None = None,
    ) -> RAGQueryAnalysis:
        key = _analysis_cache_key(query, intent)
        cached = _cached_analysis(key)
        if cached is not None:
            return cached.model_copy(deep=True)

        text = _compact(query, 800)
        lowered = text.casefold()
        terms = extract_query_terms(text)
        comparison = any(token in lowered for token in ("对比", "比较", "区别", " vs "))
        required: list[str] = []
        if any(token in text for token in ("薪资", "工资", "待遇", "收入")):
            required.append("salary")
        if any(token in text for token in ("学历", "本科", "硕士", "博士")):
            required.append("education")
        if any(token in text for token in ("经验", "年限", "应届")):
            required.append("experience")
        if any(token in lowered for token in ("技能", "技术栈", "掌握", "能力", "skill")):
            required.append("skills")
        if any(token in text for token in ("职责", "工作内容", "做什么", "任务")):
            required.append("responsibilities")
        procedural = any(
            token in text
            for token in ("怎么学", "如何学", "学习路线", "学习方向", "准备", "入门", "提升")
        )
        if procedural:
            required.extend(("skills", "responsibilities", "learning_path"))
        if comparison:
            required.append("comparison_dimensions")
        required = list(dict.fromkeys(required or ["overview"]))

        if comparison:
            question_type = "comparison"
        elif any(token in text for token in ("最近", "最新", "今年", "趋势", "当前")):
            question_type = "time_sensitive"
        elif any(token in text for token in ("比例", "分布", "平均", "多少岗位", "市场")):
            question_type = "aggregation"
        elif procedural:
            question_type = "procedural"
        elif any(token in text for token in ("总结", "概括", "归纳")):
            question_type = "summary"
        elif len(required) >= 2 or any(token in text for token in ("以及", "同时", "并且")):
            question_type = "multi_hop"
        elif any(token in text for token in ("什么是", "原理", "为什么")):
            question_type = "concept_explanation"
        elif any(token in text for token in ("某个岗位", "这份岗位", "职位详情")):
            question_type = "document_lookup"
        else:
            question_type = "fact_lookup"

        role_entities = _extract_role_entities(text)
        entities = list(dict.fromkeys([*role_entities, *self._entities(text, terms, comparison)]))
        complexity = (
            "complex"
            if question_type in {"comparison", "multi_hop"} or len(required) >= 4
            else "medium"
            if question_type in {"procedural", "aggregation", "summary", "time_sensitive"}
            else "simple"
        )
        constraints: list[str] = []
        active_filters = filters or JobKnowledgeFilters()
        if active_filters.platform:
            constraints.append(f"platform:{active_filters.platform}")
        constraints.extend(f"city:{city}" for city in active_filters.cities)
        if active_filters.education:
            constraints.append(f"education:{active_filters.education}")
        analysis = RAGQueryAnalysis(
            original_query=text,
            intent=intent,
            question_type=question_type,
            entities=entities,
            role_entities=role_entities,
            keywords=list(dict.fromkeys(terms))[:20],
            time_constraints={
                "published_after": active_filters.published_after,
                "published_before": active_filters.published_before,
            }
            if active_filters.published_after or active_filters.published_before
            else None,
            document_constraints=constraints,
            required_information=required,
            complexity=complexity,
        )
        _cache_analysis(key, analysis)
        return analysis.model_copy(deep=True)

    @staticmethod
    def _entities(query: str, terms: list[str], comparison: bool) -> list[str]:
        known = {value.casefold() for value in SKILL_ALIASES.values()}
        entities = [
            canonicalize_skill(term)
            for term in terms
            if canonicalize_skill(term).casefold() in known
        ]
        if comparison:
            parts = re.split(r"\s*(?:和|与|跟|vs\.?|对比|比较)\s*", query, flags=re.I)
            for part in parts:
                clean = re.sub(
                    r"^(?:请|帮我|分析|比较|对比)|(?:哪个.*|的区别.*|更适合.*)$",
                    "",
                    part,
                ).strip(" ，。？?")
                if 2 <= len(clean) <= 40:
                    entities.append(clean)
        return list(dict.fromkeys(item for item in entities if item))[:6]


class QueryRewriter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def rewrite(
        self,
        analysis: RAGQueryAnalysis,
        *,
        missing_information: Sequence[str] = (),
        previous_queries: Sequence[str] = (),
    ) -> RAGQueryRewrite:
        topic = " ".join(analysis.entities[:3] or analysis.keywords[:5]).strip()
        topic = topic or _compact(analysis.original_query, 160)
        needs = list(
            dict.fromkeys(
                [
                    *missing_information,
                    *analysis.required_information,
                ]
            )
        )
        labels = " ".join(_INFORMATION_QUERY_LABELS.get(item, item) for item in needs[:3])
        semantic = _compact(f"{topic} {labels or '岗位要求'}", 300)
        exact = analysis.entities[:2]
        keyword_queries: list[str] = []
        if analysis.keywords:
            keyword_queries.append(" ".join(analysis.keywords[:5]))
        sub_queries: list[str] = []
        if analysis.question_type == "comparison":
            sub_queries.extend(
                _compact(f"{entity} 岗位职责 任职要求 技能", 300)
                for entity in analysis.entities[:2]
            )
        elif analysis.question_type in {"procedural", "multi_hop"}:
            sub_queries.extend(
                _compact(f"{topic} {_INFORMATION_QUERY_LABELS.get(item, item)}", 300)
                for item in needs[:3]
            )
        elif missing_information:
            sub_queries.extend(
                _compact(f"{topic} {_INFORMATION_QUERY_LABELS.get(item, item)}", 300)
                for item in missing_information[:3]
            )

        query_limit = {"simple": 2, "medium": 4, "complex": 6}[analysis.complexity]
        query_limit = min(query_limit, self.settings.rag_max_queries)
        previous = {item.casefold().strip() for item in previous_queries}
        candidates = [semantic, *exact, *keyword_queries, *sub_queries]
        unique = list(
            dict.fromkeys(
                item for item in candidates if item and item.casefold().strip() not in previous
            )
        )[:query_limit]
        if not unique:
            unique = [semantic]
        return RAGQueryRewrite(
            semantic_query=unique[0],
            exact_queries=[item for item in exact if item in unique],
            keyword_queries=[item for item in keyword_queries if item in unique],
            sub_queries=[item for item in sub_queries if item in unique],
        )


class RetrievalPlanner:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def plan(self, analysis: RAGQueryAnalysis, filters: JobKnowledgeFilters) -> RAGRetrievalPlan:
        if analysis.question_type == "document_lookup":
            strategy = "full_text"
        elif analysis.question_type == "concept_explanation":
            strategy = "hybrid"
        else:
            strategy = "hybrid"
        section_types = sorted(
            set().union(
                *(_INFORMATION_SECTIONS.get(item, set()) for item in analysis.required_information)
            )
        )
        return RAGRetrievalPlan(
            strategy=strategy,
            vector_search=strategy in {"hybrid", "vector"},
            keyword_search=strategy in {"hybrid", "full_text"},
            metadata_filter=filters.model_dump(mode="json"),
            candidate_k=self.settings.rag_fusion_top_k,
            keyword_top_k=self.settings.rag_keyword_top_k,
            vector_top_k=self.settings.rag_vector_top_k,
            rerank_k=self.settings.rag_rerank_top_k,
            max_iterations=(
                1 if analysis.complexity == "simple" else self.settings.rag_max_iterations
            ),
            section_types=section_types,
        )


@dataclass
class RetrievalCandidate:
    citation: JobKnowledgeCitation
    reciprocal_rank_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float = 0.0
    matched_queries: set[str] = field(default_factory=set)


def _role_focus_score(
    analysis: RAGQueryAnalysis,
    candidate: RetrievalCandidate,
) -> float:
    if not analysis.role_entities:
        return 1.0
    citation = candidate.citation
    title = citation.title.casefold()
    evidence = citation.evidence.casefold()
    best = 0.0
    for role in analysis.role_entities:
        role_text = role.casefold().strip()
        if not role_text:
            continue
        if role_text in title:
            return 1.0
        anchors = [
            term.casefold()
            for term in analysis.keywords
            if term.casefold() not in _GENERIC_ROLE_TERMS and term.casefold() in role_text
        ]
        if not anchors:
            continue
        matched_anchors = [anchor for anchor in anchors if anchor in title or anchor in evidence]
        minimum_anchor_hits = max(1, math.ceil(len(anchors) * 0.6))
        if len(matched_anchors) < minimum_anchor_hits:
            continue
        anchor_in_title = any(anchor in title for anchor in matched_anchors)
        anchor_in_evidence = any(anchor in evidence for anchor in matched_anchors)
        score = (
            0.55 * _overlap(role_text, title)
            + 0.25 * _overlap(role_text, evidence)
            + (0.2 if anchor_in_title else 0.1 if anchor_in_evidence else 0.0)
        )
        best = max(best, min(1.0, score))
    return best


def _focus_candidates(
    analysis: RAGQueryAnalysis,
    candidates: Sequence[RetrievalCandidate],
) -> list[RetrievalCandidate]:
    if not analysis.role_entities:
        return list(candidates)
    focused = [
        candidate for candidate in candidates if _role_focus_score(analysis, candidate) >= 0.22
    ]
    return focused


class HybridRetriever:
    """Adapter over the existing FTS + vector + metadata implementation."""

    def __init__(self, rag: JobKnowledgeRAG) -> None:
        self.rag = rag

    async def retrieve(
        self,
        queries: Sequence[str],
        plan: RAGRetrievalPlan,
        filters: JobKnowledgeFilters,
        *,
        resume_id: UUID | None = None,
        section_types: Sequence[str] = (),
        fast_mode: bool = False,
    ) -> tuple[list[RetrievalCandidate], list[JobKnowledgeSearchResponse], list[str]]:
        candidates: dict[UUID, RetrievalCandidate] = {}
        responses: list[JobKnowledgeSearchResponse] = []
        degradations: list[str] = []
        effective_plan = plan
        query_embeddings: dict[str, list[float]] = {}
        if plan.vector_search and not fast_mode:
            try:
                query_embeddings = await self.rag.embed_queries(list(queries))
            except KnowledgeEmbeddingUnavailableError:
                effective_plan = plan.model_copy(
                    update={"strategy": "full_text", "vector_search": False}
                )
                degradations.append("批量查询向量不可用，本轮已降级为全文检索")
        for query in queries:
            request = JobKnowledgeSearchRequest(
                query=query,
                filters=filters,
                retrieval_mode=effective_plan.strategy,
                top_k=effective_plan.candidate_k,
                full_text_top_k=effective_plan.keyword_top_k,
                vector_top_k=effective_plan.vector_top_k,
                resume_id=resume_id,
                include_resume_evidence=bool(
                    resume_id and self.rag.embedding_provider is not None and not fast_mode
                ),
                section_types=list(section_types),
            )
            try:
                response = await self.rag.search(
                    request,
                    query_embedding=query_embeddings.get(query),
                )
            except KnowledgeEmbeddingUnavailableError:
                degradations.append(f"{query}：向量检索不可用，已降级为全文检索")
                response = await self.rag.search(
                    request.model_copy(update={"retrieval_mode": "full_text"})
                )
            except KnowledgeRetrievalError as exc:
                degradations.append(f"{query}：检索失败（{_compact(str(exc), 120)}）")
                continue
            except Exception as exc:
                response = None
                degradations.append(
                    f"{query}：Hybrid 检索异常，正在尝试单路降级（{_compact(str(exc), 120)}）"
                )
                fallback_modes = [
                    mode
                    for mode, enabled in (
                        ("vector", plan.vector_search),
                        ("full_text", plan.keyword_search),
                    )
                    if enabled
                ]
                for mode in fallback_modes:
                    try:
                        response = await self.rag.search(
                            request.model_copy(update={"retrieval_mode": mode})
                        )
                        degradations.append(f"{query}：已降级为 {mode} 检索")
                        break
                    except Exception:
                        continue
                if response is None:
                    degradations.append(f"{query}：所有检索通道均不可用")
                    continue
            responses.append(response)
            for citation in response.citations:
                candidate = candidates.get(citation.chunk_id)
                if candidate is None:
                    candidate = RetrievalCandidate(citation=citation)
                    candidates[citation.chunk_id] = candidate
                candidate.reciprocal_rank_score += 1.0 / (60 + citation.rank)
                candidate.matched_queries.add(query)
        max_rrf = max(
            (item.reciprocal_rank_score for item in candidates.values()),
            default=1.0,
        )
        for candidate in candidates.values():
            candidate.fused_score = candidate.reciprocal_rank_score / max(max_rrf, 1e-9)
        return list(candidates.values()), responses, degradations


class Reranker(Protocol):
    async def rerank(
        self, query: str, candidates: Sequence[RetrievalCandidate], limit: int
    ) -> list[RetrievalCandidate]: ...


class LocalEvidenceReranker:
    async def rerank(
        self, query: str, candidates: Sequence[RetrievalCandidate], limit: int
    ) -> list[RetrievalCandidate]:
        for candidate in candidates:
            citation = candidate.citation
            lexical = _overlap(query, f"{citation.title} {citation.evidence}")
            section = _SECTION_RERANK_WEIGHTS.get(citation.section_type, 0.5)
            multi_query = min(1.0, len(candidate.matched_queries) / 2)
            candidate.rerank_score = min(
                1.0,
                0.44 * candidate.fused_score
                + 0.22 * (citation.fusion_score / 100)
                + 0.2 * lexical
                + 0.09 * section
                + 0.05 * multi_query,
            )
        return sorted(
            candidates,
            key=lambda item: (item.rerank_score, item.fused_score),
            reverse=True,
        )[:limit]


class EvidenceExtractor:
    def extract(
        self,
        analysis: RAGQueryAnalysis,
        candidates: Sequence[RetrievalCandidate],
        max_items: int,
    ) -> list[RAGEvidence]:
        evidence: list[RAGEvidence] = []
        query = " ".join([analysis.original_query, *analysis.entities, *analysis.keywords])
        relevant_sections = set().union(
            *(_INFORMATION_SECTIONS.get(item, set()) for item in analysis.required_information)
        )
        for rank, candidate in enumerate(candidates, start=1):
            citation = candidate.citation
            source = RAGEvidenceSource(
                job_id=citation.job_id,
                chunk_id=citation.chunk_id,
                document_id=citation.document_id,
                parent_id=citation.parent_id,
                title=citation.title,
                company=citation.company,
                filename=citation.filename,
                section=citation.section or citation.section_type,
                page=citation.page,
                source_url=citation.source_url,
            )
            claims = _claim_lines(citation.evidence) or [_compact(citation.evidence, 420)]
            for claim in claims[:3]:
                relevance = min(
                    1.0,
                    0.62 * candidate.rerank_score
                    + 0.23 * _overlap(query, claim)
                    + 0.15 * (1.0 if citation.section_type in relevant_sections else 0.45),
                )
                if relevance < 0.28:
                    continue
                evidence_id = (
                    "ev_"
                    + hashlib.sha256(
                        f"{citation.chunk_id}:{_normalized_claim(claim)}".encode()
                    ).hexdigest()[:12]
                )
                evidence.append(
                    RAGEvidence(
                        evidence_id=evidence_id,
                        topic=citation.section_type,
                        claim=claim,
                        evidence_text=_compact(citation.evidence, 600),
                        relevance_score=round(relevance, 4),
                        source_rank=rank,
                        sources=[source],
                    )
                )
                if len(evidence) >= max_items * 2:
                    return evidence
        return evidence


class EvidenceDeduplicator:
    def deduplicate(
        self, existing: Sequence[RAGEvidence], incoming: Sequence[RAGEvidence], max_items: int
    ) -> list[RAGEvidence]:
        merged: list[RAGEvidence] = [item.model_copy(deep=True) for item in existing]
        for item in incoming:
            duplicate = next(
                (
                    current
                    for current in merged
                    if (
                        _normalized_claim(current.claim) == _normalized_claim(item.claim)
                        or self._similarity(current.claim, item.claim) >= 0.82
                    )
                ),
                None,
            )
            if duplicate is None:
                merged.append(item.model_copy(deep=True))
                continue
            duplicate.relevance_score = max(duplicate.relevance_score, item.relevance_score)
            duplicate.source_rank = min(duplicate.source_rank, item.source_rank)
            known = {source.chunk_id for source in duplicate.sources}
            duplicate.sources.extend(
                source for source in item.sources if source.chunk_id not in known
            )
            if len(item.evidence_text) > len(duplicate.evidence_text):
                duplicate.evidence_text = item.evidence_text
        merged.sort(
            key=lambda item: (item.relevance_score, len(item.sources), -item.source_rank),
            reverse=True,
        )
        return merged[:max_items]

    @staticmethod
    def _similarity(left: str, right: str) -> float:
        left_tokens = _tokens(left)
        right_tokens = _tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


class EvidenceAggregator:
    def aggregate(self, evidence: Sequence[RAGEvidence]) -> dict[str, list[RAGEvidence]]:
        groups: dict[str, list[RAGEvidence]] = defaultdict(list)
        for item in evidence:
            groups[item.topic].append(item)
        return dict(groups)


class EvidenceEvaluator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def evaluate(
        self, analysis: RAGQueryAnalysis, evidence: Sequence[RAGEvidence]
    ) -> RAGEvidenceEvaluation:
        if not evidence:
            missing = analysis.required_information or ["overview"]
            return RAGEvidenceEvaluation(
                answerable=False,
                coverage_score=0.0,
                max_relevance_score=0.0,
                missing_information=missing,
                recommended_queries=self._recommended(analysis, missing),
            )
        missing = [
            information
            for information in analysis.required_information
            if not any(self._supports_information(information, item) for item in evidence)
        ]
        if analysis.question_type == "comparison":
            corpus = " ".join(
                [
                    *(item.claim for item in evidence),
                    *(source.title for item in evidence for source in item.sources),
                ]
            )
            missing.extend(
                f"entity:{entity}"
                for entity in analysis.entities[:2]
                if _overlap(entity, corpus) < 0.5
            )
            missing = list(dict.fromkeys(missing))
        required_total = max(1, len(analysis.required_information))
        requirement_coverage = 1 - len(missing) / required_total
        source_count = len({source.job_id for item in evidence for source in item.sources})
        source_diversity = min(1.0, source_count / (2 if analysis.complexity == "simple" else 4))
        relevance = sum(item.relevance_score for item in evidence) / len(evidence)
        max_relevance = max(item.relevance_score for item in evidence)
        coverage = min(
            1.0,
            0.72 * requirement_coverage + 0.16 * source_diversity + 0.12 * relevance,
        )
        conflicts = self._conflicts(evidence)
        minimum_items = 1 if analysis.complexity == "simple" else 2
        relevance_gate = max_relevance >= self.settings.rag_evidence_min_relevance
        answerable = (
            coverage >= self.settings.rag_evidence_min_coverage
            and len(evidence) >= minimum_items
            and not missing
            and relevance_gate
        )
        return RAGEvidenceEvaluation(
            answerable=answerable,
            coverage_score=round(coverage, 4),
            max_relevance_score=round(max_relevance, 4),
            missing_information=missing,
            conflicts=conflicts,
            recommended_queries=self._recommended(analysis, missing),
        )

    @staticmethod
    def _supports_information(information: str, evidence: RAGEvidence) -> bool:
        if evidence.topic not in _INFORMATION_SECTIONS.get(information, set()):
            return False
        text = f"{evidence.claim} {evidence.evidence_text}".casefold()
        if information == "education":
            return any(term in text for term in ("学历", "本科", "硕士", "博士", "大专"))
        if information == "experience":
            return any(term in text for term in ("经验", "应届", "年限", "年以上"))
        if information == "salary":
            return any(term in text for term in ("薪资", "工资", "待遇", "元/", "k/"))
        if information == "responsibilities":
            return any(
                term in text
                for term in ("负责", "参与", "职责", "工作内容", "研发", "开发", "完成")
            )
        return True

    @staticmethod
    def _recommended(analysis: RAGQueryAnalysis, missing: Sequence[str]) -> list[str]:
        topic = " ".join(analysis.entities[:2] or analysis.keywords[:4])
        return [
            _compact(
                (
                    f"{item.removeprefix('entity:')} 岗位职责 任职要求"
                    if item.startswith("entity:")
                    else f"{topic} {_INFORMATION_QUERY_LABELS.get(item, item)}"
                ),
                300,
            )
            for item in missing[:3]
        ]

    @staticmethod
    def _conflicts(evidence: Sequence[RAGEvidence]) -> list[str]:
        conflicts: list[str] = []
        for index, left in enumerate(evidence):
            left_numbers = set(re.findall(r"\d+(?:\.\d+)?", left.claim))
            if not left_numbers:
                continue
            for right in evidence[index + 1 :]:
                if left.topic != right.topic or _overlap(left.claim, right.claim) < 0.45:
                    continue
                right_numbers = set(re.findall(r"\d+(?:\.\d+)?", right.claim))
                if right_numbers and left_numbers != right_numbers:
                    conflicts.append(f"{left.topic} 的不同岗位证据存在数值口径差异")
                    left.contradictory = True
                    right.contradictory = True
        return list(dict.fromkeys(conflicts))


class ContextBuilder:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build(self, evidence: Sequence[RAGEvidence]) -> str:
        budget = self.settings.rag_context_max_tokens
        lines = ["EVIDENCE_CONTEXT（以下内容均来自真实岗位知识库）"]
        used = estimate_tokens(lines[0])
        ratios = [
            self.settings.rag_context_primary_ratio,
            self.settings.rag_context_supporting_ratio,
            self.settings.rag_context_background_ratio,
        ]
        ratio_total = max(sum(ratios), 1e-9)
        primary = [
            item for item in evidence if not item.contradictory and item.relevance_score >= 0.72
        ]
        supporting = [
            item
            for item in evidence
            if not item.contradictory and 0.45 <= item.relevance_score < 0.72
        ]
        contradictory = [item for item in evidence if item.contradictory]
        background = [
            item for item in evidence if not item.contradictory and item.relevance_score < 0.45
        ]
        groups = [
            ("PRIMARY", primary, int(budget * ratios[0] / ratio_total)),
            ("SUPPORTING", supporting, int(budget * ratios[1] / ratio_total)),
            (
                "CONTRADICTORY",
                contradictory,
                int(budget * ratios[2] / ratio_total),
            ),
            ("BACKGROUND", background, int(budget * ratios[2] / ratio_total)),
        ]
        included: set[str] = set()
        deferred: list[tuple[str, RAGEvidence]] = []
        evidence_index = 0

        def render(tier: str, index: int, item: RAGEvidence) -> str:
            sources = "；".join(
                (f"{source.filename or source.title} / {source.section} / chunk:{source.chunk_id}")
                for source in item.sources[:3]
            )
            return (
                f"\n[E{index}] tier={tier} topic={item.topic} "
                f"relevance={item.relevance_score:.3f}\n"
                f"claim: {item.claim}\n"
                f"evidence: {_compact(item.evidence_text, 700)}\n"
                f"sources: {sources}"
            )

        for tier, items, group_budget in groups:
            group_used = 0
            for item in items:
                block = render(tier, evidence_index + 1, item)
                block_tokens = estimate_tokens(block)
                if group_used + block_tokens > group_budget:
                    deferred.append((tier, item))
                    continue
                if used + block_tokens > budget:
                    deferred.append((tier, item))
                    continue
                evidence_index += 1
                lines.append(block)
                used += block_tokens
                group_used += block_tokens
                included.add(item.evidence_id)

        # Reuse capacity left by sparse groups without changing evidence priority.
        for tier, item in deferred:
            if item.evidence_id in included:
                continue
            block = render(tier, evidence_index + 1, item)
            block_tokens = estimate_tokens(block)
            if used + block_tokens > budget:
                continue
            evidence_index += 1
            lines.append(block)
            used += block_tokens
            included.add(item.evidence_id)
        return "\n".join(lines)


class AnswerVerifier:
    """Deterministic post-check; it never invents citations or hidden reasoning."""

    def verify(self, answer: str, result: AgenticRAGSearchResponse) -> RAGVerification:
        statistics = result.search.statistics.model_dump_json()
        support = f"{result.context}\n{statistics}"
        fact_part = answer.split("## AI 建议", 1)[0]
        unsupported: list[str] = []
        for line in fact_part.splitlines():
            clean = line.strip(" -*")
            numbers = re.findall(r"\d+(?:\.\d+)?", clean)
            if numbers and any(number not in support for number in numbers):
                unsupported.append(_compact(clean, 180))
        if unsupported:
            groundedness = "partially_supported" if result.evidence else "unsupported"
        elif result.evidence:
            groundedness = "supported"
        else:
            groundedness = "partially_supported"

        missing = result.evidence_evaluation.missing_information
        completeness = (
            "complete"
            if result.evidence_evaluation.answerable and not missing
            else "partial"
            if result.evidence
            else "insufficient"
        )
        citation_ids = {citation.chunk_id for citation in result.search.citations}
        evidence_ids = {source.chunk_id for item in result.evidence for source in item.sources}
        if not citation_ids:
            citation_correctness = "unavailable"
        elif citation_ids <= evidence_ids:
            citation_correctness = "valid"
        else:
            citation_correctness = "partial"
        if (
            groundedness == "supported"
            and completeness == "complete"
            and citation_correctness == "valid"
            and not result.evidence_evaluation.conflicts
        ):
            confidence = "high"
        elif result.evidence and groundedness != "unsupported":
            confidence = "medium"
        else:
            confidence = "low"
        warnings = []
        if unsupported:
            warnings.append("部分数字型事实未在当前证据上下文中找到直接支持。")
        if missing:
            warnings.append("证据未覆盖：" + "、".join(missing))
        return RAGVerification(
            groundedness=groundedness,
            completeness=completeness,
            citation_correctness=citation_correctness,
            conflicts_handled=not result.evidence_evaluation.conflicts,
            confidence=confidence,
            unsupported_claims=unsupported[:6],
            warnings=warnings,
        )


class AgenticRAGPipeline:
    def __init__(
        self,
        rag: JobKnowledgeRAG,
        *,
        settings: Settings | None = None,
        reranker: Reranker | None = None,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.rag = rag
        self.settings = settings or get_settings()
        self.llm_provider = llm_provider
        self.analyzer = QueryAnalyzer()
        self.rewriter = QueryRewriter(self.settings)
        self.planner = RetrievalPlanner(self.settings)
        self.retriever = HybridRetriever(rag)
        if reranker is None and self.settings.rag_reranker == "cross_encoder":
            from app.llm.local_semantic import SemanticReranker

            reranker = SemanticReranker(
                self.settings.semantic_reranker_model, self.settings.semantic_cache_dir
            )
        self.reranker = reranker or LocalEvidenceReranker()
        self.extractor = EvidenceExtractor()
        self.deduplicator = EvidenceDeduplicator()
        self.aggregator = EvidenceAggregator()
        self.evaluator = EvidenceEvaluator(self.settings)
        self.context_builder = ContextBuilder(self.settings)
        self.llm_planner = LLMRetrievalPlanner(llm_provider, self.settings)
        self.evidence_reflector = EvidenceReflectionService(llm_provider, self.settings)
        self.answer_reflector = AnswerReflectionService(llm_provider, self.settings)

    def _rewrite_from_plan(
        self,
        plan: RAGRetrievalPlan,
        analysis: RAGQueryAnalysis,
        *,
        missing_information: Sequence[str] = (),
        previous_queries: Sequence[str] = (),
    ) -> RAGQueryRewrite:
        if not plan.planned_queries:
            return self.rewriter.rewrite(
                analysis,
                missing_information=missing_information,
                previous_queries=previous_queries,
            )
        planned = [item.query for item in plan.planned_queries if item.query.strip()]
        planned = [
            query
            for query in planned
            if query.casefold() not in {item.casefold() for item in previous_queries}
        ][: self.settings.rag_max_queries]
        if not planned:
            return self.rewriter.rewrite(
                analysis,
                missing_information=missing_information,
                previous_queries=previous_queries,
            )
        by_purpose = {item.query: item.purpose for item in plan.planned_queries}
        return RAGQueryRewrite(
            semantic_query=planned[0],
            exact_queries=[query for query in planned[1:] if by_purpose.get(query) == "exact"],
            keyword_queries=[
                query
                for query in planned[1:]
                if by_purpose.get(query) in {"keyword", "aggregation"}
            ],
            sub_queries=[
                query
                for query in planned[1:]
                if by_purpose.get(query) in {"comparison", "procedural"}
            ],
        )

    def _repair_queries(
        self,
        reflection: RAGEvidenceReflection,
        *,
        previous_queries: Sequence[str],
    ) -> list[str]:
        previous = {item.casefold().strip() for item in previous_queries}
        queries: list[str] = []
        for action in reflection.repair_actions:
            query = (action.query or action.target_dimension or "").strip()
            if not query and action.action == "expand_query":
                query = "岗位要求 技能 经验 学历 薪资"
            if query and query.casefold() not in previous and query.casefold() not in {
                item.casefold() for item in queries
            }:
                queries.append(query)
        return queries[: self.settings.rag_max_queries]

    async def reflect_answer(
        self,
        answer: str,
        result: AgenticRAGSearchResponse,
        verification: RAGVerification,
    ) -> tuple[Any, dict[str, Any], str | None]:
        try:
            return await asyncio.wait_for(
                self.answer_reflector.reflect(answer, verification, result.evidence),
                timeout=self.settings.rag_workflow_timeout_seconds,
            )
        except TimeoutError:
            return (
                RAGAnswerReflection(status="insufficient"),
                {},
                "LLM 回答校验超时，已保留原回答并标记为待核实",
            )

    def repair_answer(self, reflection: Any) -> str:
        return self.answer_reflector.local_repair(reflection)

    async def run(
        self,
        request: JobKnowledgeSearchRequest,
        *,
        intent: str = "knowledge_query",
        on_status: RAGStatusCallback | None = None,
    ) -> AgenticRAGSearchResponse:
        trace_id = str(uuid4())
        latency: dict[str, float] = {}
        degradations: list[str] = []

        async def emit(event_type: str, payload: dict) -> None:
            if on_status is not None:
                await on_status(event_type, {"trace_id": trace_id, **payload})

        started = perf_counter()
        workflow_deadline = started + self.settings.rag_workflow_timeout_seconds
        await emit("retrieval_status", {"stage": "query_analysis", "label": "正在分析问题结构"})
        analysis = self.analyzer.analyze(request.query, intent=intent, filters=request.filters)
        latency["query_analysis"] = round((perf_counter() - started) * 1000, 2)
        indexing_in_progress = await self.rag.knowledge_update_in_progress()

        planning_started = perf_counter()
        rule_plan = self.planner.plan(analysis, request.filters)
        plan = rule_plan
        planner_usage: dict[str, Any] = {}
        planner_warning: str | None = None
        if not indexing_in_progress and self.llm_planner.should_use(analysis):
            try:
                llm_plan, planner_usage, planner_warning = await asyncio.wait_for(
                    self.llm_planner.plan(
                        analysis,
                        rule_plan,
                        request.filters,
                    ),
                    timeout=max(0.1, workflow_deadline - perf_counter()),
                )
            except TimeoutError:
                llm_plan, planner_usage, planner_warning = (
                    None,
                    {},
                    "LLM 检索规划超时，已回退规则规划",
                )
            if llm_plan is not None and not self.settings.rag_planner_shadow_mode:
                plan = llm_plan
            elif llm_plan is not None and self.settings.rag_planner_shadow_mode:
                planner_warning = "LLM 检索规划处于影子模式，当前仍使用规则规划执行"
            if planner_warning:
                degradations.append(planner_warning)
        rewrite = self._rewrite_from_plan(plan, analysis)
        if indexing_in_progress:
            plan = plan.model_copy(
                update={
                    "strategy": "full_text",
                    "vector_search": False,
                    "keyword_search": True,
                    "candidate_k": min(20, plan.candidate_k),
                    "keyword_top_k": min(30, plan.keyword_top_k),
                    "rerank_k": min(8, plan.rerank_k),
                    "max_iterations": 1,
                    "planner_source": "rules",
                    "planner_confidence": 1.0,
                    "plan_version": "fast-indexing-v1",
                }
            )
            rewrite = RAGQueryRewrite(semantic_query=analysis.original_query)
            degradations.append("知识库正在增量更新，已切换为单次快速全文检索")
        latency["planning"] = round((perf_counter() - planning_started) * 1000, 2)
        await emit(
            "retrieval_status",
            {
                "stage": "retrieval_planning",
                "label": (
                    "知识库正在增量更新，检索速度可能降低"
                    if indexing_in_progress
                    else f"已生成 {len(rewrite.all_queries)} 个受控检索查询"
                ),
                "question_type": analysis.question_type,
                "strategy": plan.strategy,
                "planner_source": plan.planner_source,
            },
        )

        searched_queries: list[str] = []
        all_candidates: dict[UUID, RetrievalCandidate] = {}
        responses: list[JobKnowledgeSearchResponse] = []
        evidence: list[RAGEvidence] = []
        evaluation = RAGEvidenceEvaluation(
            answerable=False,
            coverage_score=0,
            missing_information=analysis.required_information,
        )
        reranked: list[RetrievalCandidate] = []
        iterations_run = 0
        reflection_iterations = 0
        reflection_records: list[dict[str, Any]] = []
        reflection_usage: dict[str, Any] = {}
        repair_actions: list[str] = []
        repair_queries: list[str] = []
        coverage_before = 0.0
        coverage_after = 0.0
        stop_reason = ""

        retrieval_started = perf_counter()
        for iteration in range(plan.max_iterations):
            if perf_counter() >= workflow_deadline:
                stop_reason = "workflow_timeout"
                degradations.append("Agentic RAG 达到工作流超时上限，已保留当前证据")
                break
            evidence_count_before = len(evidence)
            current_rewrite = (
                rewrite
                if iteration == 0
                else self._rewrite_from_plan(
                    plan,
                    analysis,
                    missing_information=evaluation.missing_information,
                    previous_queries=searched_queries,
                )
            )
            if iteration > 0 and repair_queries:
                current_rewrite = RAGQueryRewrite(
                    semantic_query=repair_queries[0],
                    keyword_queries=repair_queries[1:],
                )
                repair_queries = []
            remaining_query_budget = max(0, self.settings.rag_max_queries - len(searched_queries))
            if remaining_query_budget == 0:
                stop_reason = "query_budget_exhausted"
                break
            iteration_query_limit = remaining_query_budget
            if iteration == 0 and plan.max_iterations > 1:
                iteration_query_limit = max(1, remaining_query_budget - 2)
            queries = [
                query
                for query in current_rewrite.all_queries
                if query.casefold() not in {item.casefold() for item in searched_queries}
            ]
            queries = _merge_similar_queries(queries, iteration_query_limit)
            if indexing_in_progress:
                queries = queries[:1]
            if not queries:
                stop_reason = "no_new_queries"
                break
            iterations_run += 1
            await emit(
                "retrieval_status",
                {
                    "stage": "retrieving",
                    "label": f"正在进行第 {iteration + 1} 轮知识库检索",
                    "iteration": iteration + 1,
                    "query_count": len(queries),
                },
            )
            iteration_sections = plan.section_types
            if iteration > 0 and evaluation.missing_information:
                iteration_sections = (
                    sorted(
                        set().union(
                            *(
                                _INFORMATION_SECTIONS.get(item, set())
                                for item in evaluation.missing_information
                                if not item.startswith("entity:")
                            )
                        )
                    )
                    or plan.section_types
                )
            try:
                (
                    candidates,
                    iteration_responses,
                    iteration_degradations,
                ) = await asyncio.wait_for(
                    self.retriever.retrieve(
                        queries,
                        plan,
                        request.filters,
                        resume_id=request.resume_id,
                        section_types=iteration_sections,
                        fast_mode=indexing_in_progress,
                    ),
                    timeout=max(0.1, workflow_deadline - perf_counter()),
                )
            except TimeoutError:
                stop_reason = "workflow_timeout"
                degradations.append("知识库检索达到工作流超时上限，已保留当前证据")
                break
            if analysis.role_entities:
                focused_candidates = _focus_candidates(analysis, candidates)
                removed_count = len(candidates) - len(focused_candidates)
                if focused_candidates:
                    candidates = focused_candidates
                    if removed_count:
                        degradations.append(f"已排除 {removed_count} 条偏离目标岗位的候选内容")
                elif candidates:
                    candidates = []
                    degradations.append(
                        "未找到满足目标岗位实体约束的可靠候选，已拒绝使用泛岗位结果替代"
                    )
            searched_queries.extend(queries)
            responses.extend(iteration_responses)
            degradations.extend(iteration_degradations)
            for candidate in candidates:
                existing = all_candidates.get(candidate.citation.chunk_id)
                if existing is None:
                    all_candidates[candidate.citation.chunk_id] = candidate
                    continue
                existing.reciprocal_rank_score += candidate.reciprocal_rank_score
                existing.fused_score = max(existing.fused_score, candidate.fused_score)
                existing.matched_queries.update(candidate.matched_queries)
            await emit(
                "retrieval_status",
                {
                    "stage": "reranking",
                    "label": f"已召回 {len(all_candidates)} 条候选内容，正在重排",
                    "candidate_count": len(all_candidates),
                },
            )
            try:
                reranked = await self.reranker.rerank(
                    analysis.original_query,
                    list(all_candidates.values()),
                    plan.rerank_k,
                )
            except Exception as exc:
                degradations.append(f"Reranker 不可用，已使用融合排序：{_compact(str(exc), 120)}")
                reranked = sorted(
                    all_candidates.values(),
                    key=lambda item: item.fused_score,
                    reverse=True,
                )[: plan.rerank_k]
            extracted = self.extractor.extract(
                analysis, reranked, self.settings.rag_evidence_max_items
            )
            evidence = self.deduplicator.deduplicate(
                evidence, extracted, self.settings.rag_evidence_max_items
            )
            self.aggregator.aggregate(evidence)
            evaluation = self.evaluator.evaluate(analysis, evidence)
            coverage_after = evaluation.coverage_score
            if iteration == 0:
                coverage_before = evaluation.coverage_score
            await emit(
                "evidence_status",
                {
                    "stage": "evidence_evaluation",
                    "label": (
                        "证据已充分" if evaluation.answerable else "证据覆盖不足，准备补充检索"
                    ),
                    "iteration": iteration + 1,
                    "evidence_count": len(evidence),
                    "coverage_score": evaluation.coverage_score,
                    "missing_information": evaluation.missing_information,
                },
            )
            if evaluation.answerable:
                stop_reason = "evidence_sufficient"
                break
            if iteration > 0 and (
                evaluation.coverage_score - coverage_before < self.settings.rag_min_evidence_gain
                and len(evidence) <= evidence_count_before
            ):
                stop_reason = "insufficient_evidence_gain"
                break
            if iteration >= plan.max_iterations - 1:
                stop_reason = "reflection_budget_exhausted"
                break
            if self.settings.rag_max_reflection_iterations <= reflection_iterations:
                stop_reason = "reflection_budget_exhausted"
                break
            reflection_iterations += 1
            try:
                (
                    reflection,
                    reflection_usage,
                    reflection_warning,
                ) = await asyncio.wait_for(
                    self.evidence_reflector.reflect(
                        analysis,
                        evaluation,
                        evidence,
                        iteration=iteration,
                        max_iterations=plan.max_iterations,
                        previous_queries=searched_queries,
                    ),
                    timeout=max(0.1, workflow_deadline - perf_counter()),
                )
            except TimeoutError:
                stop_reason = "workflow_timeout"
                degradations.append("证据反思达到工作流超时上限，已保留当前证据")
                break
            reflection_records.append(reflection.model_dump(mode="json"))
            if reflection_warning:
                degradations.append(reflection_warning)
            repair_actions.extend(action.action for action in reflection.repair_actions)
            repair_queries = self._repair_queries(reflection, previous_queries=searched_queries)
            if not repair_queries:
                repair_queries = self.rewriter.rewrite(
                    analysis,
                    missing_information=evaluation.missing_information,
                    previous_queries=searched_queries,
                ).all_queries
            await emit(
                "evidence_status",
                {
                    "stage": "evidence_reflection",
                    "label": reflection.decision_summary or "正在根据证据缺口定向修复检索",
                    "iteration": iteration + 1,
                    "reflection_status": reflection.status,
                    "repair_actions": [action.action for action in reflection.repair_actions],
                },
            )
            if reflection.status != "repairable" and not repair_queries:
                stop_reason = "reflection_not_repairable"
                break
        latency["retrieval_and_evidence"] = round((perf_counter() - retrieval_started) * 1000, 2)

        if responses:
            primary = responses[0]
        elif indexing_in_progress:
            stop_reason = stop_reason or "fast_mode_no_retry"
            primary = self.rag.empty_response(
                request,
                warnings=["知识库正在增量更新，本轮快速检索未命中，已返回当前已有结果。"],
            )
        else:
            remaining = workflow_deadline - perf_counter()
            if remaining <= 0.05:
                stop_reason = stop_reason or "workflow_timeout"
                primary = self.rag.empty_response(
                    request,
                    warnings=["知识库检索已达到时间上限，已立即返回当前已有结果。"],
                )
            else:
                try:
                    primary = await asyncio.wait_for(
                        self.rag.search(
                            request.model_copy(
                                update={
                                    "retrieval_mode": "full_text",
                                    "include_resume_evidence": False,
                                }
                            )
                        ),
                        timeout=remaining,
                    )
                except TimeoutError:
                    stop_reason = stop_reason or "workflow_timeout"
                    primary = self.rag.empty_response(
                        request,
                        warnings=["知识库检索已达到时间上限，已立即返回当前已有结果。"],
                    )
                except Exception as exc:
                    stop_reason = stop_reason or "retrieval_fallback_failed"
                    primary = self.rag.empty_response(
                        request,
                        warnings=[
                            "知识库快速兜底检索失败，已返回当前已有结果："
                            f"{_compact(str(exc), 120)}"
                        ],
                    )
            responses.append(primary)
        evidence_chunk_ids = {source.chunk_id for item in evidence for source in item.sources}
        selected_candidates = [
            item for item in reranked if item.citation.chunk_id in evidence_chunk_ids
        ] or reranked
        citations = [
            item.citation.model_copy(
                update={
                    "citation_index": index,
                    "rank": index,
                    "fusion_score": round(item.rerank_score * 100, 2),
                    "retrieval_sources": list(
                        dict.fromkeys(
                            [
                                *item.citation.retrieval_sources,
                                "agentic_rrf",
                                "evidence_pipeline",
                            ]
                        )
                    ),
                }
            )
            for index, item in enumerate(
                selected_candidates[: self.settings.rag_evidence_max_items], start=1
            )
        ]
        focused_job_ids = list(
            dict.fromkeys(
                item.citation.job_id
                for item in selected_candidates
                if item.citation.chunk_id in evidence_chunk_ids
            )
        )
        focused_statistics = (
            await self.rag.statistics_for_jobs(focused_job_ids)
            if analysis.role_entities
            else primary.statistics
        )
        warnings = list(
            dict.fromkeys(
                [
                    *focused_statistics.warnings,
                    *degradations,
                    *(
                        ["当前证据不足以完整回答：" + "、".join(evaluation.missing_information)]
                        if evaluation.missing_information
                        else []
                    ),
                    *(
                        ["不同岗位证据存在口径差异，回答中应显式说明。"]
                        if evaluation.conflicts
                        else []
                    ),
                    *(
                        [
                            "候选内容与问题的直接相关性不足，未将语义近邻岗位视为确定答案。"
                        ]
                        if evidence
                        and evaluation.max_relevance_score
                        < self.settings.rag_evidence_min_relevance
                        else []
                    ),
                ]
            )
        )
        search = primary.model_copy(
            update={
                "query": request.query,
                "retrieval_mode": plan.strategy,
                "citations": citations,
                "sample_count": focused_statistics.sample_count,
                "statistics": focused_statistics,
                "data_as_of": focused_statistics.data_as_of,
                "filters": request.filters,
                "warnings": warnings,
                "cache_hit": bool(responses) and all(item.cache_hit for item in responses),
            }
        )
        context_started = perf_counter()
        context = self.context_builder.build(evidence)
        latency["context_building"] = round((perf_counter() - context_started) * 1000, 2)
        knowledge_status = (
            "sufficient" if evaluation.answerable else "partial" if evidence else "insufficient"
        )
        confidence = (
            "high"
            if evaluation.coverage_score >= 0.85
            and len({source.job_id for item in evidence for source in item.sources}) >= 3
            and not evaluation.conflicts
            else "medium"
            if evidence and evaluation.coverage_score >= 0.45
            else "low"
        )
        evidence_yield = len(evidence) / max(1, len(all_candidates))
        trace = RAGTrace(
            trace_id=trace_id,
            retrieval_iterations=iterations_run,
            query_count=len(searched_queries),
            candidate_count=len(all_candidates),
            reranked_count=len(reranked),
            evidence_count=len(evidence),
            searched_queries=searched_queries,
            latency_ms=latency,
            metrics={
                "evidence_coverage": evaluation.coverage_score,
                "evidence_max_relevance": evaluation.max_relevance_score,
                "evidence_yield": round(evidence_yield, 4),
                "mrr_proxy": round(1 / min((item.source_rank for item in evidence), default=1), 4),
                "reranker_evidence_hit_rate": round(
                    len(evidence_chunk_ids) / max(1, len(reranked)), 4
                ),
            },
            degradations=degradations,
            planner_source=plan.planner_source,
            planner_confidence=plan.planner_confidence,
            reflection_iterations=reflection_iterations,
            repair_actions=list(dict.fromkeys(repair_actions)),
            coverage_before=coverage_before,
            coverage_after=coverage_after,
            stop_reason=stop_reason,
            planner_token_usage=planner_usage,
            reflection_token_usage=reflection_usage,
            plan_version=plan.plan_version,
            reflection=reflection_records,
        )
        return AgenticRAGSearchResponse(
            search=search,
            query_analysis=analysis,
            query_rewrite=rewrite,
            retrieval_plan=plan,
            evidence=evidence,
            evidence_evaluation=evaluation,
            context=context,
            trace=trace,
            knowledge_status=knowledge_status,
            confidence=confidence,
            warnings=warnings,
        )


def agentic_rag_prompt_payload(result: AgenticRAGSearchResponse) -> str:
    """Compact, source-bound context for the answer model."""
    statistics = result.search.statistics.model_dump(mode="json")
    statistics["skills"] = [
        {key: value for key, value in item.items() if key != "job_ids"}
        for item in statistics.get("skills", [])[:12]
    ]
    payload = {
        "knowledge_status": result.knowledge_status,
        "confidence": result.confidence,
        "max_relevance_score": result.evidence_evaluation.max_relevance_score,
        "required_information": result.query_analysis.required_information,
        "missing_information": result.evidence_evaluation.missing_information,
        "conflicts": result.evidence_evaluation.conflicts,
        "statistics": statistics,
        "evidence_context": result.context[:5000],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
