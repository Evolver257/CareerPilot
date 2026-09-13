from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import Float, case, cast, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.llm.provider import LLMProvider, embed_texts
from app.models.entities import (
    Company,
    Job,
    JobKnowledgeChunk,
    JobKnowledgeDocument,
    JobSkillFact,
    KnowledgeIndexRun,
    Resume,
    SkillTaxonomy,
)
from app.repositories.matching import MatchingRepository
from app.schemas.knowledge_search import (
    JobKnowledgeCitation,
    JobKnowledgeFilters,
    JobKnowledgeSearchRequest,
    JobKnowledgeSearchResponse,
    JobKnowledgeStatistics,
    KnowledgeDistributionItem,
    KnowledgeSalaryBand,
    KnowledgeSkillDemand,
    ResumeKnowledgeEvidence,
)
from app.services.job_knowledge import (
    JOB_KNOWLEDGE_VERSION,
    SKILL_ALIASES,
    canonicalize_skill,
    normalize_experience_requirement,
)
from app.services.resume_rag import ResumeRAG


class KnowledgeRetrievalError(ValueError):
    """Raised when a requested knowledge retrieval operation cannot run."""


class KnowledgeEmbeddingUnavailableError(KnowledgeRetrievalError):
    pass


class KnowledgeEmbeddingIncompatibleError(KnowledgeEmbeddingUnavailableError):
    """The configured query vector cannot be compared with stored vectors."""

    pass


@dataclass
class _ChunkHit:
    chunk: JobKnowledgeChunk
    job: Job
    company_name: str | None
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    full_rank: int | None = None
    vector_rank: int | None = None
    sources: set[str] = field(default_factory=set)
    fusion_score: float = 0.0
    rerank_score: float = 0.0


_SEARCH_CACHE: OrderedDict[str, tuple[float, JobKnowledgeSearchResponse]] = OrderedDict()
_SEARCH_CACHE_TTL_SECONDS = 60.0
_SEARCH_CACHE_MAX_SIZE = 128
_QUERY_EMBED_CACHE: OrderedDict[str, tuple[float, list[float]]] = OrderedDict()
_QUERY_EMBED_CACHE_TTL_SECONDS = 300.0
_QUERY_EMBED_CACHE_MAX_SIZE = 512
_SECTION_WEIGHTS = {
    "required_skills": 1.0,
    "requirements": 0.98,
    "responsibilities": 0.94,
    "overview": 0.88,
    "direction": 0.86,
    "education": 0.82,
    "experience": 0.82,
    "salary_benefits": 0.7,
    "preferred_skills": 0.68,
    "business_domain": 0.65,
    "source_context": 0.55,
    "other": 0.45,
}
_SALARY_UNIT_LABELS = {
    "cny_day": "元/天",
    "cny_month_k": "K/月",
    "cny_year_wan": "万元/年",
}
_QUERY_STOP_PHRASES = (
    "我想了解",
    "我想学习",
    "想学习",
    "需要掌握哪些",
    "需要掌握",
    "有哪些",
    "有什么",
    "怎么样",
    "如何",
    "请问",
    "相关岗位",
    "岗位需求",
    "岗位要求",
    "任职条件",
    "技术栈",
    "学习方向",
    "学习",
    "方向",
    "还有",
    "其他",
    "建议",
    "继续",
    "吗",
    "呢",
)
_DOMAIN_QUERY_TERMS = (
    "人工智能",
    "机器学习",
    "深度学习",
    "自然语言处理",
    "计算机视觉",
    "大模型",
    "智能体",
    "机器人控制",
    "控制算法",
    "机器人",
    "后端开发",
    "前端开发",
    "全栈",
    "数据分析",
    "数据工程",
    "产品经理",
    "网络安全",
    "算法",
)
_QUERY_CONCEPT_EXPANSIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("企鹅操作系统", "类 unix", "类unix"), ("Linux", "Shell")),
    (("命令行", "终端命令"), ("Linux", "Shell", "Bash")),
    (
        ("生成答案质量", "答案质量", "模型质量", "评估生成结果", "验证生成答案"),
        ("模型评测", "评测集", "评估体系"),
    ),
    (
        ("模型服务上线", "模型上线", "更快响应", "推理速度", "推理延迟"),
        ("模型部署", "推理优化", "vLLM", "TensorRT"),
    ),
    (("外部工具", "调用工具", "执行查询和操作"), ("Function Calling", "Tool Calling")),
    (("企业实践", "在校实践", "还在读书"), ("实习", "实习生")),
)


def clear_knowledge_search_cache() -> None:
    _SEARCH_CACHE.clear()
    _QUERY_EMBED_CACHE.clear()


def _now() -> datetime:
    return datetime.now(UTC)


def _dialect_name(session: AsyncSession) -> str:
    return session.get_bind().dialect.name


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return _clamp(dot / (left_norm * right_norm))


def _tokens(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    tokens = {
        token for token in re.findall(r"[a-z0-9][a-z0-9+#._/-]*", normalized) if len(token) > 1
    }
    for segment in re.findall(r"[\u3400-\u9fff]+", normalized):
        tokens.update(f"zh2:{segment[index : index + 2]}" for index in range(len(segment) - 1))
        if len(segment) >= 3:
            tokens.update(f"zh3:{segment[index : index + 3]}" for index in range(len(segment) - 2))
    return tokens


def _query_terms(query: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", query.casefold()).strip()
    terms: list[str] = []
    matched_canonicals: set[str] = set()

    for alias, canonical in sorted(SKILL_ALIASES.items(), key=lambda item: -len(item[0])):
        canonical_key = canonical.casefold()
        if canonical_key in matched_canonicals:
            continue
        if re.search(r"[a-z0-9]", alias):
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized):
                terms.extend((alias, canonical))
                matched_canonicals.add(canonical_key)
        elif alias in normalized:
            terms.extend((alias, canonical))
            matched_canonicals.add(canonical_key)

    if not terms:
        terms.extend(
            token for token in re.findall(r"[a-z0-9][a-z0-9+#._/-]*", normalized) if len(token) > 1
        )
    terms.extend(term for term in _DOMAIN_QUERY_TERMS if term in normalized)
    for cues, expansions in _QUERY_CONCEPT_EXPANSIONS:
        if any(cue in normalized for cue in cues):
            terms.extend(expansions)

    if not terms:
        for segment in re.findall(r"[\u3400-\u9fff]{2,}", normalized):
            cleaned = segment
            for phrase in _QUERY_STOP_PHRASES:
                cleaned = cleaned.replace(phrase, " ")
            terms.extend(part for part in cleaned.split() if len(part) >= 2)

    return list(
        dict.fromkeys(
            term.strip()
            for term in terms
            if len(term.strip()) >= 2 and term.strip() not in _QUERY_STOP_PHRASES
        )
    )[:20]


def section_weights_for_query(query: str) -> dict[str, float]:
    """Adjust section authority to the information requested by the user."""

    weights = dict(_SECTION_WEIGHTS)
    lowered = query.casefold()
    intents: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (
            ("技能", "技术栈", "掌握", "熟悉", "能力", "skill"),
            ("required_skills", "requirements", "preferred_skills"),
        ),
        (("学历", "本科", "硕士", "博士", "大专"), ("education", "requirements")),
        (("经验", "年限", "应届"), ("experience", "requirements")),
        (("薪资", "工资", "待遇", "收入"), ("salary_benefits", "overview")),
        (("职责", "工作内容", "做什么", "任务"), ("responsibilities", "requirements")),
        (
            ("方向", "岗位类型", "职位类别", "岗位族群"),
            ("direction", "overview", "business_domain"),
        ),
    ]
    matched = [sections for cues, sections in intents if any(cue in lowered for cue in cues)]
    if not matched:
        return weights
    requested = set().union(*matched)
    for section in weights:
        if section in requested:
            weights[section] = max(0.92, min(1.0, weights[section] + 0.16))
        elif section == "source_context":
            weights[section] = 0.48
        else:
            weights[section] = max(0.3, weights[section] * 0.68)
    return weights


def extract_query_terms(query: str) -> list[str]:
    """Public, stable adapter used by query understanding and retrieval."""
    return _query_terms(query)


def _lexical_score(query: str, job: Job, company_name: str | None, content: str) -> float:
    query_terms = _query_terms(query)
    concepts = " ".join(query_terms) or query
    query_tokens = _tokens(concepts)
    if not query_tokens:
        return 0.0
    title_tokens = _tokens(job.title)
    company_tokens = _tokens(company_name or "")
    content_tokens = _tokens(content)
    overlap = len(query_tokens & content_tokens) / max(1, len(query_tokens))
    title_overlap = len(query_tokens & title_tokens) / max(1, len(query_tokens))
    company_overlap = len(query_tokens & company_tokens) / max(1, len(query_tokens))
    phrase_bonus = 0.0
    title_lower = job.title.casefold()
    content_lower = content.casefold()
    phrase_terms = [term.casefold() for term in query_terms]
    if any(term in title_lower for term in phrase_terms):
        phrase_bonus = 0.35
    elif any(term in content_lower for term in phrase_terms):
        phrase_bonus = 0.15
    return _clamp(0.55 * overlap + 0.3 * title_overlap + 0.15 * company_overlap + phrase_bonus)


def _distribution(values: list[str]) -> list[KnowledgeDistributionItem]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value or "未注明"] += 1
    total = max(1, len(values))
    return [
        KnowledgeDistributionItem(
            label=label,
            count=count,
            percentage=round(count / total * 100, 1),
        )
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _normalize_education(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "未注明"
    if "不限" in text or "无要求" in text:
        return "学历不限"
    if "博士" in text:
        return "博士及以上"
    if "硕士" in text:
        return "硕士及以上"
    if "本科" in text:
        return "本科及以上"
    if "大专" in text or "专科" in text:
        return "大专及以上"
    return text[:30]


def _normalize_experience(value: str | None) -> str:
    return normalize_experience_requirement(value) or "未注明"


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _salary_bands(rows: list[tuple[str, int | None, int | None]]) -> list[KnowledgeSalaryBand]:
    groups: dict[str, list[float]] = defaultdict(list)
    for unit, low, high in rows:
        values = [float(value) for value in (low, high) if value is not None]
        if values and unit:
            groups[unit].append(float(median(values)))
    result: list[KnowledgeSalaryBand] = []
    for unit, values in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        result.append(
            KnowledgeSalaryBand(
                unit=unit,
                unit_label=_SALARY_UNIT_LABELS.get(unit, unit or "未注明"),
                sample_count=len(values),
                minimum=round(min(values), 1),
                p25=round(_percentile(values, 0.25), 1),
                median=round(_percentile(values, 0.5), 1),
                p75=round(_percentile(values, 0.75), 1),
                maximum=round(max(values), 1),
            )
        )
    return result


def _filter_job_types(values: list[str]) -> set[str]:
    normalized = {value.strip() for value in values if value.strip()}
    lowered = {value.casefold() for value in normalized}
    if lowered & {"实习", "intern", "internship"}:
        normalized.update({"实习", "Intern", "Internship", "internship"})
    if lowered & {"全职", "full-time", "fulltime"}:
        normalized.update({"全职", "Full-time", "Fulltime", "full-time"})
    return normalized


class JobKnowledgeRAG:
    """Hybrid retrieval over the independently indexed job knowledge base."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: LLMProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.settings = settings or get_settings()
        self.matching_repository = MatchingRepository(session)

    async def knowledge_update_in_progress(self) -> bool:
        """Return whether a full rebuild is active without touching embeddings.

        Incremental runs deliberately do not participate in this switch. They
        write new documents while previously completed chunks remain valid and
        searchable, so a small import must never downgrade the whole knowledge
        base to a slower full-text-only path.
        """

        run_id = await self.session.scalar(
            select(KnowledgeIndexRun.id)
            .where(KnowledgeIndexRun.status.in_(["PENDING", "RUNNING"]))
            .where(KnowledgeIndexRun.mode == "backfill")
            .limit(1)
        )
        return run_id is not None

    @staticmethod
    def empty_response(
        request: JobKnowledgeSearchRequest,
        *,
        warnings: list[str] | None = None,
    ) -> JobKnowledgeSearchResponse:
        response_warnings = list(warnings or [])
        statistics = JobKnowledgeStatistics(sample_count=0, warnings=response_warnings.copy())
        return JobKnowledgeSearchResponse(
            query=request.query.strip(),
            retrieval_mode="full_text",
            knowledge_version=JOB_KNOWLEDGE_VERSION,
            generated_at=_now(),
            sample_count=0,
            filters=request.filters,
            statistics=statistics,
            warnings=response_warnings,
        )

    async def embed_queries(self, queries: list[str]) -> dict[str, list[float]]:
        """Embed unique query texts in one batch and cache the vectors briefly."""

        provider = self.embedding_provider
        if provider is None:
            raise KnowledgeEmbeddingUnavailableError(
                "当前检索模式需要 Embedding Provider，但系统未配置可用 Provider。"
            )
        requested_queries = [query for query in queries if query.strip()]
        normalized_queries: dict[str, str] = {}
        for query in requested_queries:
            normalized = re.sub(r"\s+", " ", query.casefold()).strip()
            normalized_queries.setdefault(normalized, query)
        unique_queries = list(normalized_queries.values())
        if not unique_queries:
            return {}
        signature = str(getattr(provider, "embedding_signature", "") or "")
        provider_name = str(getattr(provider, "provider_name", type(provider).__name__))
        cache_prefix = json.dumps(
            [
                provider_name,
                signature,
                self.settings.embedding_model,
                self.settings.embedding_dimensions,
            ],
            ensure_ascii=False,
        )
        vectors_by_normalized: dict[str, list[float]] = {}
        missing: list[tuple[str, str]] = []
        now = time.monotonic()
        for query in unique_queries:
            normalized = re.sub(r"\s+", " ", query.casefold()).strip()
            cache_key = f"{cache_prefix}:{normalized}"
            cached = _QUERY_EMBED_CACHE.get(cache_key)
            if cached is not None and now - cached[0] <= _QUERY_EMBED_CACHE_TTL_SECONDS:
                _QUERY_EMBED_CACHE.move_to_end(cache_key)
                vectors_by_normalized[normalized] = list(cached[1])
                continue
            if cached is not None:
                _QUERY_EMBED_CACHE.pop(cache_key, None)
            missing.append((query, cache_key))
        if missing:
            texts = [query for query, _ in missing]
            try:
                encode = getattr(provider, "encode", None)
                if provider_name == "sentence_transformers" and callable(encode):
                    # LocalSemanticProvider uses a query prompt for Qwen. Its
                    # generic embed_many method intentionally uses document
                    # mode, so preserve query semantics for this batch.
                    vectors = await asyncio.to_thread(encode, texts, is_query=True)
                else:
                    vectors = await embed_texts(
                        provider,
                        texts,
                        model=self.settings.embedding_model,
                    )
            except Exception as exc:
                raise KnowledgeEmbeddingUnavailableError(
                    "向量检索失败，请检查 Embedding Provider 配置后重试。"
                ) from exc
            if len(vectors) != len(missing):
                raise KnowledgeRetrievalError(
                    f"查询向量数量不匹配：期望 {len(missing)}，实际 {len(vectors)}"
                )
            for (query, cache_key), vector in zip(missing, vectors, strict=True):
                normalized_vector = list(vector)
                if len(normalized_vector) != self.settings.embedding_dimensions:
                    raise KnowledgeEmbeddingIncompatibleError(
                        "向量维度不兼容："
                        f"岗位知识库要求 {self.settings.embedding_dimensions} 维，"
                        f"当前为 {len(normalized_vector)} 维。"
                    )
                _QUERY_EMBED_CACHE[cache_key] = (now, normalized_vector)
                _QUERY_EMBED_CACHE.move_to_end(cache_key)
                normalized_query = re.sub(r"\s+", " ", query.casefold()).strip()
                vectors_by_normalized[normalized_query] = normalized_vector
            while len(_QUERY_EMBED_CACHE) > _QUERY_EMBED_CACHE_MAX_SIZE:
                _QUERY_EMBED_CACHE.popitem(last=False)
        return {
            query: list(vectors_by_normalized[normalized])
            for query in requested_queries
            for normalized in [re.sub(r"\s+", " ", query.casefold()).strip()]
            if normalized in vectors_by_normalized
        }

    async def search(
        self,
        request: JobKnowledgeSearchRequest,
        *,
        query_embedding: list[float] | None = None,
    ) -> JobKnowledgeSearchResponse:
        if (
            request.filters.salary_floor is not None
            and request.filters.salary_ceiling is not None
            and request.filters.salary_floor > request.filters.salary_ceiling
        ):
            raise KnowledgeRetrievalError("薪资下限不能高于薪资上限")

        rebuild_in_progress = await self.knowledge_update_in_progress()
        if rebuild_in_progress:
            request = request.model_copy(
                update={
                    "retrieval_mode": "full_text",
                    "full_text_top_k": min(request.full_text_top_k, 30),
                    "include_resume_evidence": False,
                    "rerank_mode": "local",
                }
            )

        watermark = await self._knowledge_watermark()
        resume_watermark = await self._resume_watermark(request)
        embedding_signature = str(getattr(self.embedding_provider, "embedding_signature", "") or "")
        cache_key = self._cache_key(request, watermark, resume_watermark, embedding_signature)
        if not request.force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached.model_copy(update={"cache_hit": True})

        terms = _query_terms(request.query)
        job_ids = await self._matching_job_ids(
            request.filters,
            request.query,
            terms,
            request.section_types,
        )
        warnings: list[str] = (
            ["知识库正在全量重建，当前使用快速全文检索。"] if rebuild_in_progress else []
        )
        hits: dict[UUID, _ChunkHit] = {}
        if request.retrieval_mode in {"hybrid", "full_text"}:
            full_text_hits = await self._full_text_retrieve(
                request.filters,
                request.query,
                terms,
                request.full_text_top_k,
                request.section_types,
            )
            self._merge_hits(hits, full_text_hits, "full_text")
        if request.retrieval_mode in {"hybrid", "vector"}:
            if self.embedding_provider is None and request.retrieval_mode == "hybrid":
                warnings.append("未配置 Embedding Provider，本次仅使用全文召回。")
            else:
                try:
                    vector_hits = await self._vector_retrieve(
                        request.filters,
                        request.query,
                        request.vector_top_k,
                        request.section_types,
                        query_embedding=query_embedding,
                    )
                except KnowledgeEmbeddingIncompatibleError:
                    if request.retrieval_mode != "hybrid":
                        raise
                    warnings.append("查询向量维度不兼容，本次已降级为全文召回。")
                else:
                    self._merge_hits(hits, vector_hits, "vector")
        if hits:
            job_ids = list(dict.fromkeys([*job_ids, *(hit.job.id for hit in hits.values())]))
        statistics = await self.statistics_for_jobs(job_ids)
        warnings = [*statistics.warnings, *warnings]

        ranked = self._fuse_and_rerank(hits, request.retrieval_mode, request.query)
        if request.rerank_mode == "none":
            ranked.sort(key=lambda hit: hit.fusion_score, reverse=True)
            for hit in ranked:
                hit.rerank_score = hit.fusion_score
        elif request.rerank_mode == "cross_encoder":
            import asyncio

            from app.core.config import get_settings
            from app.llm.local_semantic import SemanticReranker

            settings = get_settings()
            reranker = SemanticReranker(
                settings.semantic_reranker_model, settings.semantic_cache_dir
            )
            pool = ranked[:40]
            try:
                scores = await asyncio.to_thread(
                    reranker.predict,
                    request.query,
                    [f"{hit.job.title}\n{hit.chunk.content}" for hit in pool],
                )
                for hit, score in zip(pool, scores, strict=True):
                    hit.rerank_score = 1 / (1 + math.exp(-max(-40, min(40, score))))
                ranked = [
                    item
                    for _, item in sorted(
                        zip(scores, pool, strict=True), key=lambda pair: pair[0], reverse=True
                    )
                ]
            except Exception as exc:
                raise KnowledgeRetrievalError("语义重排失败，未静默使用规则结果") from exc
        selected = self._select_diverse(ranked, request.top_k)
        citations = [self._citation(index, hit) for index, hit in enumerate(selected, start=1)]
        resume_evidence: list[ResumeKnowledgeEvidence] = []
        if request.include_resume_evidence:
            resume_evidence = await self._resume_evidence(request, selected)

        if not citations and not job_ids:
            warnings.append("知识库中没有符合当前查询和筛选条件的已索引岗位。")
        result = JobKnowledgeSearchResponse(
            reranker=request.rerank_mode,
            query=request.query.strip(),
            retrieval_mode=request.retrieval_mode,
            knowledge_version=JOB_KNOWLEDGE_VERSION,
            generated_at=_now(),
            data_as_of=statistics.data_as_of,
            sample_count=statistics.sample_count,
            filters=request.filters,
            statistics=statistics,
            citations=citations,
            resume_evidence=resume_evidence,
            warnings=list(dict.fromkeys(warnings)),
        )
        self._cache_put(cache_key, result)
        return result

    async def statistics(self, request: JobKnowledgeSearchRequest) -> JobKnowledgeStatistics:
        terms = _query_terms(request.query)
        job_ids = await self._matching_job_ids(
            request.filters,
            request.query,
            terms,
            request.section_types,
        )
        return await self.statistics_for_jobs(job_ids)

    async def statistics_for_jobs(self, job_ids: list[UUID]) -> JobKnowledgeStatistics:
        if not job_ids:
            return JobKnowledgeStatistics(
                sample_count=0,
                warnings=["知识库中没有符合当前查询和筛选条件的已索引岗位。"],
            )
        rows = list(
            (
                await self.session.execute(
                    select(
                        JobKnowledgeDocument.job_id,
                        JobKnowledgeDocument.salary_unit,
                        JobKnowledgeDocument.salary_min,
                        JobKnowledgeDocument.salary_max,
                        JobKnowledgeDocument.normalized_education,
                        JobKnowledgeDocument.normalized_experience,
                        JobKnowledgeDocument.updated_at,
                    ).where(
                        JobKnowledgeDocument.active.is_(True),
                        JobKnowledgeDocument.knowledge_version == JOB_KNOWLEDGE_VERSION,
                        JobKnowledgeDocument.job_id.in_(job_ids),
                    )
                )
            ).all()
        )
        by_job: dict[UUID, tuple[Any, ...]] = {}
        for row in rows:
            by_job.setdefault(row.job_id, tuple(row))
        salary_rows = [(str(row[1] or ""), row[2], row[3]) for row in by_job.values()]
        education = _distribution([_normalize_education(row[4]) for row in by_job.values()])
        experience = _distribution([_normalize_experience(row[5]) for row in by_job.values()])
        skill_rows = list(
            (
                await self.session.execute(
                    select(
                        SkillTaxonomy.id,
                        SkillTaxonomy.canonical_name,
                        SkillTaxonomy.category,
                        func.count(distinct(JobSkillFact.job_id)),
                        func.sum(case((JobSkillFact.requirement_type == "required", 1), else_=0)),
                        func.sum(case((JobSkillFact.requirement_type == "preferred", 1), else_=0)),
                        func.sum(case((JobSkillFact.requirement_type == "inferred", 1), else_=0)),
                    )
                    .join(JobSkillFact, JobSkillFact.skill_id == SkillTaxonomy.id)
                    .where(JobSkillFact.job_id.in_(list(by_job)))
                    .group_by(
                        SkillTaxonomy.id,
                        SkillTaxonomy.canonical_name,
                        SkillTaxonomy.category,
                    )
                    .order_by(func.count(distinct(JobSkillFact.job_id)).desc())
                    .limit(50)
                )
            ).all()
        )
        fact_rows = list(
            (
                await self.session.execute(
                    select(JobSkillFact.skill_id, JobSkillFact.job_id).where(
                        JobSkillFact.job_id.in_(list(by_job))
                    )
                )
            ).all()
        )
        skill_jobs: dict[UUID, list[UUID]] = defaultdict(list)
        for skill_id, job_id in fact_rows:
            if job_id not in skill_jobs[skill_id]:
                skill_jobs[skill_id].append(job_id)
        sample_count = len(by_job)
        skills = [
            KnowledgeSkillDemand(
                name=str(row[1]),
                category=str(row[2] or "other"),
                count=int(row[3] or 0),
                percentage=round(int(row[3] or 0) / max(1, sample_count) * 100, 1),
                required_count=int(row[4] or 0),
                preferred_count=int(row[5] or 0),
                inferred_count=int(row[6] or 0),
                job_ids=skill_jobs.get(row[0], [])[:20],
            )
            for row in skill_rows
        ]
        warnings: list[str] = []
        if sample_count < 5:
            warnings.append("当前样本少于 5 个岗位，统计结论仅供参考。")
        if not _salary_bands(salary_rows):
            warnings.append("当前样本没有可识别的薪资数据。")
        data_as_of = max((row[6] for row in by_job.values() if row[6] is not None), default=None)
        return JobKnowledgeStatistics(
            sample_count=sample_count,
            data_as_of=data_as_of,
            salary_bands=_salary_bands(salary_rows),
            education_distribution=education,
            experience_distribution=experience,
            skills=skills,
            warnings=warnings,
        )

    async def _matching_job_ids(
        self,
        filters: JobKnowledgeFilters,
        query: str,
        terms: list[str],
        section_types: list[str] | None = None,
    ) -> list[UUID]:
        statement = (
            select(distinct(Job.id))
            .select_from(JobKnowledgeChunk)
            .join(JobKnowledgeDocument, JobKnowledgeChunk.document_id == JobKnowledgeDocument.id)
            .join(Job, JobKnowledgeChunk.job_id == Job.id)
            .outerjoin(Company, Job.company_id == Company.id)
            .where(*self._base_conditions(filters, section_types))
        )
        query_condition = self._query_condition(query, terms)
        if query_condition is not None:
            statement = statement.where(query_condition)
        return list((await self.session.scalars(statement)).all())

    def _base_conditions(
        self,
        filters: JobKnowledgeFilters,
        section_types: list[str] | None = None,
    ) -> list[Any]:
        conditions: list[Any] = [
            JobKnowledgeDocument.active.is_(True),
            JobKnowledgeDocument.knowledge_version == JOB_KNOWLEDGE_VERSION,
            Job.lifecycle_status != "expired",
            or_(
                Job.data_quality_score.is_(None),
                Job.data_quality_score >= self.settings.rag_min_quality_score,
            ),
        ]
        if filters.cities:
            conditions.append(
                or_(
                    *(
                        JobKnowledgeDocument.normalized_city.ilike(f"%{city}%")
                        for city in filters.cities
                    )
                )
            )
        if filters.education:
            conditions.append(
                JobKnowledgeDocument.normalized_education.ilike(f"%{filters.education}%")
            )
        if filters.experience:
            conditions.append(
                JobKnowledgeDocument.normalized_experience.ilike(f"%{filters.experience}%")
            )
        if filters.job_types:
            conditions.append(
                JobKnowledgeDocument.employment_type.in_(_filter_job_types(filters.job_types))
            )
        if filters.platform:
            conditions.append(Job.platform == filters.platform)
        if filters.salary_floor is not None:
            conditions.append(
                func.coalesce(JobKnowledgeDocument.salary_max, JobKnowledgeDocument.salary_min)
                >= filters.salary_floor
            )
        if filters.salary_ceiling is not None:
            conditions.append(
                func.coalesce(JobKnowledgeDocument.salary_min, JobKnowledgeDocument.salary_max)
                <= filters.salary_ceiling
            )
        if filters.published_after is not None:
            conditions.append(Job.publish_time >= filters.published_after)
        if filters.published_before is not None:
            conditions.append(Job.publish_time <= filters.published_before)
        if filters.collected_after is not None:
            conditions.append(Job.last_collected_at >= filters.collected_after)
        if filters.job_ids:
            conditions.append(Job.id.in_(filters.job_ids))
        if section_types:
            conditions.append(JobKnowledgeChunk.section_type.in_(section_types))
        return conditions

    def _query_condition(self, query: str, terms: list[str]) -> Any | None:
        if not query.strip() or not terms:
            return None
        lexical = []
        expanded_terms = list(terms)
        for term in terms:
            canonical = canonicalize_skill(term)
            if canonical.casefold() != term.casefold():
                expanded_terms.append(canonical)
        for term in list(dict.fromkeys(expanded_terms)):
            pattern = f"%{term}%"
            lexical.extend(
                [
                    Job.title.ilike(pattern),
                    Job.description.ilike(pattern),
                    JobKnowledgeChunk.content.ilike(pattern),
                    Company.name.ilike(pattern),
                ]
            )
        if _dialect_name(self.session) != "postgresql":
            return or_(*lexical)
        tsvector = func.to_tsvector("simple", JobKnowledgeChunk.content)
        job_tsvector = func.to_tsvector(
            "simple",
            func.coalesce(Job.title, "") + " " + func.coalesce(Job.description, ""),
        )
        tsquery = func.plainto_tsquery("simple", query)
        return or_(tsvector.op("@@")(tsquery), job_tsvector.op("@@")(tsquery), *lexical)

    async def _full_text_retrieve(
        self,
        filters: JobKnowledgeFilters,
        query: str,
        terms: list[str],
        limit: int,
        section_types: list[str] | None = None,
    ) -> list[_ChunkHit]:
        query_condition = self._query_condition(query, terms)
        if query_condition is None:
            return []
        statement = (
            select(JobKnowledgeChunk, JobKnowledgeDocument, Job, Company.name)
            .select_from(JobKnowledgeChunk)
            .join(JobKnowledgeDocument, JobKnowledgeChunk.document_id == JobKnowledgeDocument.id)
            .join(Job, JobKnowledgeChunk.job_id == Job.id)
            .outerjoin(Company, Job.company_id == Company.id)
            .where(*self._base_conditions(filters, section_types), query_condition)
        )
        if _dialect_name(self.session) == "postgresql":
            tsvector = func.to_tsvector("simple", JobKnowledgeChunk.content)
            job_tsvector = func.to_tsvector(
                "simple",
                func.coalesce(Job.title, "") + " " + func.coalesce(Job.description, ""),
            )
            tsquery = func.plainto_tsquery("simple", query)
            rank = func.ts_rank_cd(tsvector, tsquery) + func.ts_rank_cd(job_tsvector, tsquery)
            statement = statement.add_columns(rank.label("search_rank")).order_by(rank.desc())
        else:
            statement = statement.order_by(
                Job.updated_at.desc(), JobKnowledgeChunk.created_at.desc()
            )
        rows = list((await self.session.execute(statement.limit(limit))).all())
        hits: list[_ChunkHit] = []
        for row in rows:
            chunk, _, job, company_name = row[:4]
            raw_rank = float(row[4] or 0.0) if len(row) > 4 else 0.0
            hits.append(
                _ChunkHit(
                    chunk=chunk,
                    job=job,
                    company_name=company_name,
                    lexical_score=_clamp(
                        max(raw_rank, _lexical_score(query, job, company_name, chunk.content))
                    ),
                )
            )
        hits.sort(key=lambda hit: hit.lexical_score, reverse=True)
        for rank, hit in enumerate(hits, start=1):
            hit.full_rank = rank
        return hits

    async def _vector_retrieve(
        self,
        filters: JobKnowledgeFilters,
        query: str,
        limit: int,
        section_types: list[str] | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[_ChunkHit]:
        provider = self.embedding_provider
        if provider is None:
            raise KnowledgeEmbeddingUnavailableError(
                "当前检索模式需要 Embedding Provider，但系统未配置可用 Provider。"
            )
        if query_embedding is None:
            try:
                query_embedding = (await self.embed_queries([query])).get(query)
            except Exception as exc:
                if isinstance(exc, KnowledgeEmbeddingUnavailableError):
                    raise
                raise KnowledgeEmbeddingUnavailableError(
                    "向量检索失败，请检查 Embedding Provider 配置后重试。"
                ) from exc
        if query_embedding is None:
            raise KnowledgeEmbeddingUnavailableError("未生成查询向量")
        if len(query_embedding) != self.settings.embedding_dimensions:
            raise KnowledgeEmbeddingIncompatibleError(
                "向量维度不兼容："
                f"岗位知识库要求 {self.settings.embedding_dimensions} 维，"
                f"当前为 {len(query_embedding)} 维。"
            )
        signature = str(getattr(provider, "embedding_signature", "") or "")
        conditions = [
            *self._base_conditions(filters, section_types),
            JobKnowledgeChunk.embedding.is_not(None),
            JobKnowledgeChunk.embedding_dimensions == self.settings.embedding_dimensions,
        ]
        if signature:
            conditions.append(JobKnowledgeChunk.embedding_signature == signature)
        statement = (
            select(JobKnowledgeChunk, JobKnowledgeDocument, Job, Company.name)
            .select_from(JobKnowledgeChunk)
            .join(JobKnowledgeDocument, JobKnowledgeChunk.document_id == JobKnowledgeDocument.id)
            .join(Job, JobKnowledgeChunk.job_id == Job.id)
            .outerjoin(Company, Job.company_id == Company.id)
            .where(*conditions)
        )
        hits: list[_ChunkHit] = []
        if _dialect_name(self.session) == "postgresql":
            distance = cast(JobKnowledgeChunk.embedding.op("<=>")(query_embedding), Float)
            rows = list(
                (
                    await self.session.execute(
                        statement.add_columns(distance.label("distance"))
                        .order_by(distance)
                        .limit(limit)
                    )
                ).all()
            )
            for row in rows:
                chunk, _, job, company_name, distance_value = row
                hits.append(
                    _ChunkHit(
                        chunk=chunk,
                        job=job,
                        company_name=company_name,
                        semantic_score=_clamp(1.0 - float(distance_value)),
                    )
                )
        else:
            rows = list((await self.session.execute(statement)).all())
            for row in rows:
                chunk, _, job, company_name = row
                hits.append(
                    _ChunkHit(
                        chunk=chunk,
                        job=job,
                        company_name=company_name,
                        semantic_score=_cosine_similarity(
                            query_embedding, list(chunk.embedding or [])
                        ),
                    )
                )
            hits.sort(key=lambda hit: hit.semantic_score, reverse=True)
            hits = hits[:limit]
        for rank, hit in enumerate(hits, start=1):
            hit.vector_rank = rank
        return hits

    @staticmethod
    def _merge_hits(target: dict[UUID, _ChunkHit], hits: list[_ChunkHit], source: str) -> None:
        for hit in hits:
            existing = target.get(hit.chunk.id)
            if existing is None:
                hit.sources.add(source)
                target[hit.chunk.id] = hit
                continue
            existing.sources.add(source)
            if hit.lexical_score > existing.lexical_score:
                existing.lexical_score = hit.lexical_score
                existing.full_rank = hit.full_rank
            if hit.semantic_score > existing.semantic_score:
                existing.semantic_score = hit.semantic_score
                existing.vector_rank = hit.vector_rank

    def _fuse_and_rerank(
        self,
        hits: dict[UUID, _ChunkHit],
        mode: str,
        query: str,
    ) -> list[_ChunkHit]:
        if not hits:
            return []
        section_weights = section_weights_for_query(query)
        max_rrf = 0.0
        max_rrf = max(max_rrf, 1e-9)
        for hit in hits.values():
            rrf = 0.0
            weight_total = max(
                1e-9, self.settings.rag_sparse_weight + self.settings.rag_dense_weight
            )
            if hit.full_rank is not None:
                rrf += (self.settings.rag_sparse_weight / weight_total) / (
                    self.settings.rag_rrf_k + hit.full_rank
                )
            if hit.vector_rank is not None:
                rrf += (self.settings.rag_dense_weight / weight_total) / (
                    self.settings.rag_rrf_k + hit.vector_rank
                )
            hit.fusion_score = rrf
            max_rrf = max(max_rrf, rrf)
        for hit in hits.values():
            rrf_score = hit.fusion_score / max_rrf
            title_score = _lexical_score(query, hit.job, hit.company_name, hit.job.title)
            section_score = section_weights.get(hit.chunk.section_type, 0.5)
            if mode == "full_text":
                base = 0.8 * hit.lexical_score + 0.2 * rrf_score
            elif mode == "vector":
                base = 0.82 * hit.semantic_score + 0.18 * rrf_score
            else:
                base = 0.48 * rrf_score + 0.27 * hit.lexical_score + 0.25 * hit.semantic_score
            hit.fusion_score = _clamp(base)
            hit.rerank_score = _clamp(
                0.78 * hit.fusion_score + 0.14 * title_score + 0.08 * section_score
            )
        return sorted(
            hits.values(),
            key=lambda hit: (hit.rerank_score, hit.fusion_score, hit.job.updated_at),
            reverse=True,
        )

    @staticmethod
    def _select_diverse(hits: list[_ChunkHit], top_k: int) -> list[_ChunkHit]:
        selected: list[_ChunkHit] = []
        job_counts: dict[UUID, int] = defaultdict(int)
        company_counts: dict[str, int] = defaultdict(int)
        for company_limit in (1, 2):
            for hit in hits:
                company_key = (hit.company_name or f"job:{hit.job.id}").casefold()
                if job_counts[hit.job.id] >= 2 or company_counts[company_key] >= company_limit:
                    continue
                selected.append(hit)
                job_counts[hit.job.id] += 1
                company_counts[company_key] += 1
                if len(selected) >= top_k:
                    return selected
        return selected

    @staticmethod
    def _citation(index: int, hit: _ChunkHit) -> JobKnowledgeCitation:
        metadata = hit.chunk.chunk_metadata or {}
        parent_id = metadata.get("parent_id") or hit.chunk.document_id
        try:
            parent_uuid = UUID(str(parent_id)) if parent_id else None
        except ValueError:
            parent_uuid = hit.chunk.document_id
        page_value = metadata.get("page")
        page = (
            int(page_value)
            if isinstance(page_value, int | str) and str(page_value).isdigit()
            else None
        )
        return JobKnowledgeCitation(
            citation_index=index,
            job_id=hit.job.id,
            chunk_id=hit.chunk.id,
            title=hit.job.title,
            company=hit.company_name,
            location=hit.job.location,
            platform=hit.job.platform,
            source_url=hit.job.source_url,
            document_id=hit.chunk.document_id,
            parent_id=parent_uuid,
            filename=str(metadata.get("filename") or f"{hit.job.platform}-{hit.job.title}"),
            section=str(metadata.get("section") or hit.chunk.section_type),
            page=page,
            document_type=str(metadata.get("document_type") or "job_description"),
            section_type=hit.chunk.section_type,
            evidence=hit.chunk.content,
            retrieval_sources=sorted(hit.sources),
            lexical_score=round(hit.lexical_score * 100, 2),
            semantic_score=round(hit.semantic_score * 100, 2),
            fusion_score=round(hit.rerank_score * 100, 2),
            rank=index,
        )

    async def _resume_evidence(
        self,
        request: JobKnowledgeSearchRequest,
        selected: list[_ChunkHit],
    ) -> list[ResumeKnowledgeEvidence]:
        if self.embedding_provider is None:
            raise KnowledgeEmbeddingUnavailableError(
                "结合简历检索需要 Embedding Provider，但系统未配置可用 Provider。"
            )
        resume: Resume | None
        if request.resume_id:
            resume = await self.matching_repository.get_resume(request.resume_id)
        else:
            resume = await self.matching_repository.get_default_resume()
        if resume is None:
            raise KnowledgeRetrievalError("未找到可用于检索的简历")
        rag = ResumeRAG(self.matching_repository, self.embedding_provider, self.settings)
        evidence: list[ResumeKnowledgeEvidence] = []
        seen: set[UUID] = set()
        for hit in selected[:3]:
            for item in (await rag.retrieve(hit.job, resume))[:3]:
                if item.chunk_id in seen:
                    continue
                seen.add(item.chunk_id)
                evidence.append(
                    ResumeKnowledgeEvidence(
                        job_id=hit.job.id,
                        chunk_id=item.chunk_id,
                        chunk_type=item.chunk_type,
                        content=item.content,
                        metadata=item.metadata,
                        rerank_score=item.rerank_score,
                    )
                )
        return evidence[:9]

    async def _knowledge_watermark(self) -> str:
        count, document_latest, job_latest = (
            await self.session.execute(
                select(
                    func.count(distinct(JobKnowledgeDocument.job_id)),
                    func.max(JobKnowledgeDocument.updated_at),
                    func.max(Job.updated_at),
                )
                .select_from(JobKnowledgeDocument)
                .join(Job, JobKnowledgeDocument.job_id == Job.id)
                .where(
                    JobKnowledgeDocument.active.is_(True),
                    JobKnowledgeDocument.knowledge_version == JOB_KNOWLEDGE_VERSION,
                )
            )
        ).one()
        return json.dumps(
            [
                count or 0,
                document_latest.isoformat() if document_latest else "",
                job_latest.isoformat() if job_latest else "",
            ],
            ensure_ascii=False,
        )

    async def _resume_watermark(self, request: JobKnowledgeSearchRequest) -> str:
        if not request.include_resume_evidence:
            return "none"
        resume = (
            await self.matching_repository.get_resume(request.resume_id)
            if request.resume_id
            else await self.matching_repository.get_default_resume()
        )
        if resume is None:
            return "missing"
        return json.dumps(
            [
                str(resume.id),
                resume.version,
                resume.updated_at.isoformat() if resume.updated_at else "",
            ],
            ensure_ascii=False,
        )

    @staticmethod
    def _cache_key(
        request: JobKnowledgeSearchRequest,
        watermark: str,
        resume_watermark: str,
        embedding_signature: str,
    ) -> str:
        payload = {
            "query": re.sub(r"\s+", " ", request.query.casefold()).strip(),
            "filters": request.filters.model_dump(mode="json"),
            "retrieval_mode": request.retrieval_mode,
            "rerank_mode": request.rerank_mode,
            "reranker_model": get_settings().semantic_reranker_model
            if request.rerank_mode == "cross_encoder"
            else None,
            "top_k": request.top_k,
            "full_text_top_k": request.full_text_top_k,
            "vector_top_k": request.vector_top_k,
            "include_resume_evidence": request.include_resume_evidence,
            "resume_watermark": resume_watermark,
            "knowledge_version": JOB_KNOWLEDGE_VERSION,
            "embedding_signature": embedding_signature,
            "watermark": watermark,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    @classmethod
    def _cache_get(cls, key: str) -> JobKnowledgeSearchResponse | None:
        cached = _SEARCH_CACHE.get(key)
        if cached is None:
            return None
        created_at, response = cached
        if time.monotonic() - created_at > _SEARCH_CACHE_TTL_SECONDS:
            _SEARCH_CACHE.pop(key, None)
            return None
        _SEARCH_CACHE.move_to_end(key)
        return response

    @classmethod
    def _cache_put(cls, key: str, response: JobKnowledgeSearchResponse) -> None:
        _SEARCH_CACHE[key] = (time.monotonic(), response)
        _SEARCH_CACHE.move_to_end(key)
        while len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX_SIZE:
            _SEARCH_CACHE.popitem(last=False)
