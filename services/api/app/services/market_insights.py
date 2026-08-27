from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.llm.provider import LLMProvider
from app.models.entities import Job, MarketInsightReport, User
from app.repositories.market_insights import MarketInsightRepository
from app.schemas.market_insights import (
    DistributionItem,
    EvidenceJob,
    LearningPhase,
    MarketInsightCreate,
    MarketInsightLLMOutput,
    MarketInsightResult,
    ResponsibilityTheme,
    RoleCluster,
    SalaryBand,
    SkillInsight,
)
from app.services.llm_settings import LLMSettingsService


class MarketInsightNotFoundError(ValueError):
    pass


class MarketInsightActionError(ValueError):
    pass


THEMES: list[tuple[str, tuple[str, ...]]] = [
    ("算法研究与方案设计", ("算法", "论文", "调研", "复现", "research", "方案设计")),
    ("模型训练与优化", ("训练", "调参", "模型优化", "pytorch", "tensorflow", "微调")),
    ("数据处理与评估", ("数据", "清洗", "标注", "评估", "测试", "指标")),
    ("仿真与机器人控制", ("仿真", "isaac", "mujoco", "gazebo", "控制", "规划", "sim2real")),
    ("工程实现与部署", ("部署", "工程", "接口", "服务", "性能优化", "上线", "开发")),
    ("产品协作与交付", ("产品", "协作", "需求", "交付", "沟通", "文档")),
]
MARKET_INSIGHT_VERSION = "market-insight-v2"
MARKET_INSIGHT_PROMPT_VERSION = "market-insight-compact-v1"
MARKET_INSIGHT_LLM_MAX_TOKENS = 1200


def _now() -> datetime:
    return datetime.now(UTC)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _round(value: float) -> float:
    return round(value, 1)


def _query_terms(query: str) -> list[str]:
    lowered = query.lower().strip()
    terms = {lowered}
    terms.update(re.findall(r"[a-z][a-z0-9+.#-]{1,}|[\u4e00-\u9fff]{2,}", lowered))
    stop = {"岗位", "方向", "工作", "职位", "要求", "学习", "相关", "想做", "希望", "了解"}
    for chunk in list(terms):
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", chunk):
            cleaned = chunk
            for suffix in ("实习生", "工程师", "专家", "岗位", "方向", "职位"):
                cleaned = cleaned.replace(suffix, "")
            if len(cleaned) >= 2:
                terms.add(cleaned)
            terms.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return sorted(
        (term for term in terms if term not in stop and len(term) >= 2), key=len, reverse=True
    )


def _job_text(job: Job) -> str:
    structured = job.normalized_data.get("structured_job", {}) if job.normalized_data else {}
    return " ".join(
        [
            job.title,
            job.description,
            str(structured.get("role_category", "")),
            " ".join(skill.skill_name for skill in job.skills),
        ]
    ).lower()


def _relevance(job: Job, query: str, terms: list[str]) -> float:
    title = job.title.lower()
    description = job.description.lower()
    skills = " ".join(skill.skill_name for skill in job.skills).lower()
    score = 0.0
    if query.lower() in title:
        score += 16
    for term in terms:
        weight = min(6.0, max(1.0, len(term) / 2))
        is_ascii = bool(re.fullmatch(r"[a-z0-9+.# -]+", term))

        def contains(value: str) -> bool:
            if not is_ascii:
                return term in value
            return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", value))

        if contains(title):
            score += 3.0 * weight
        elif contains(skills):
            score += 2.0 * weight
        elif contains(description):
            score += 0.7 * weight
    return score


def _salary_text(job: Job) -> str | None:
    raw = job.raw_data or {}
    for key in ("salary_text", "salary", "salaryText"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if job.salary_min is None and job.salary_max is None:
        return None
    suffix = "元/天" if (job.job_type or "").lower() in {"internship", "实习"} else "K/月"
    low = job.salary_min if job.salary_min is not None else job.salary_max
    high = job.salary_max if job.salary_max is not None else job.salary_min
    return f"{low}-{high}{suffix}"


def _salary_unit(job: Job) -> tuple[str, str] | None:
    text = (_salary_text(job) or "").lower()
    if "元/天" in text or "/天" in text or "daily" in text:
        return "cny_day", "元/天"
    if "万/年" in text or "万元/年" in text:
        return "cny_year_wan", "万元/年"
    if "k" in text or "千/月" in text:
        return "cny_month_k", "K/月"
    if job.salary_min is not None:
        if (job.job_type or "").lower() in {"internship", "实习"} and job.salary_min >= 50:
            return "cny_day", "元/天"
        if job.salary_min <= 100:
            return "cny_month_k", "K/月"
    return None


def _education(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return "未注明"
    if "不限" in text or "无要求" in text:
        return "学历不限"
    matches = [
        (text.find(keyword), label)
        for keyword, label in (
            ("博士", "博士"),
            ("硕士", "硕士及以上"),
            ("本科", "本科及以上"),
            ("大专", "大专及以上"),
            ("专科", "大专及以上"),
        )
        if keyword in text
    ]
    if matches:
        return min(matches, key=lambda item: item[0])[1]
    return text[:30]


def _experience(value: str | None) -> str:
    text = (value or "").strip().lower()
    if not text:
        return "未注明"
    if any(token in text for token in ("不限", "无经验", "应届", "在校", "实习")):
        return "应届/经验不限"
    numbers = [int(item) for item in re.findall(r"(\d+)\s*年", text)]
    if numbers:
        low = min(numbers)
        high = max(numbers)
        if high <= 1:
            return "1年以内"
        if low <= 3:
            return "1-3年"
        if low <= 5:
            return "3-5年"
        return "5年以上"
    if "经验" in text and any(token in text for token in ("优先", "具备", "拥有", "丰富")):
        return "相关项目经验优先"
    return "未注明"


def _distribution(values: list[str]) -> list[DistributionItem]:
    counts = Counter(values)
    total = max(1, len(values))
    return [
        DistributionItem(label=label, count=count, percentage=_round(count / total * 100))
        for label, count in counts.most_common()
    ]


def _llm_digest(result: MarketInsightResult) -> dict[str, Any]:
    """Keep only decision-relevant aggregates; never send job IDs or full JDs."""
    return {
        "query": result.query,
        "sample_count": result.sample_count,
        "confidence": result.confidence,
        "salary": [
            {
                "unit": item.unit_label,
                "samples": item.sample_count,
                "median": item.median,
                "p25": item.p25,
                "p75": item.p75,
            }
            for item in result.salary_bands[:2]
        ],
        "education": [
            {"label": item.label, "percentage": item.percentage}
            for item in result.education_distribution[:3]
        ],
        "experience": [
            {"label": item.label, "percentage": item.percentage}
            for item in result.experience_distribution[:3]
        ],
        "skills": [
            {
                "name": item.name,
                "percentage": item.percentage,
                "category": item.category,
            }
            for item in result.skills[:12]
        ],
        "responsibilities": [
            {
                "name": item.name,
                "percentage": item.percentage,
                "example": item.examples[0][:100] if item.examples else "",
            }
            for item in result.responsibility_themes[:6]
        ],
        "role_clusters": [
            {"name": item.name, "percentage": item.percentage} for item in result.role_clusters[:5]
        ],
        "roadmap": [
            {"weeks": item.weeks, "title": item.title, "skills": item.skills[:4]}
            for item in result.learning_roadmap
        ],
    }


class MarketInsightAggregator:
    def build(
        self,
        query: str,
        ranked_jobs: list[tuple[Job, float]],
    ) -> MarketInsightResult:
        jobs = [job for job, _ in ranked_jobs]
        sample_count = len(jobs)
        confidence = (
            "high" if sample_count >= 10 else "medium" if sample_count >= 5 else "insufficient"
        )
        warnings: list[str] = []
        if sample_count < 5:
            warnings.append("相关岗位样本少于 5 条，统计仅供参考；建议先采集更多 BOSS 职位。")

        salary_groups: dict[tuple[str, str], list[float]] = defaultdict(list)
        for job in jobs:
            unit = _salary_unit(job)
            values = [value for value in (job.salary_min, job.salary_max) if value is not None]
            if unit and values:
                salary_groups[unit].append(float(median(values)))
        salary_bands = [
            SalaryBand(
                unit=unit,
                unit_label=label,
                sample_count=len(values),
                minimum=_round(min(values)),
                p25=_round(_percentile(values, 0.25)),
                median=_round(_percentile(values, 0.5)),
                p75=_round(_percentile(values, 0.75)),
                maximum=_round(max(values)),
            )
            for (unit, label), values in sorted(
                salary_groups.items(), key=lambda item: len(item[1]), reverse=True
            )
        ]
        if not salary_bands:
            warnings.append("样本中缺少可识别的薪资区间。")

        skill_stats: dict[str, dict[str, Any]] = {}
        for job in jobs:
            seen: set[str] = set()
            for skill in job.skills:
                name = skill.skill_name.strip()
                key = name.lower()
                if not name or key in seen:
                    continue
                seen.add(key)
                stats = skill_stats.setdefault(
                    key, {"name": name, "count": 0, "required": 0, "preferred": 0, "jobs": []}
                )
                stats["count"] += 1
                stats["required" if skill.skill_type == "required" else "preferred"] += 1
                stats["jobs"].append(job.id)
        skills: list[SkillInsight] = []
        for stats in skill_stats.values():
            percentage = stats["count"] / max(1, sample_count) * 100
            if stats["required"] / max(1, sample_count) >= 0.5:
                category = "core"
            elif percentage >= 25:
                category = "high_frequency"
            elif stats["preferred"] > stats["required"]:
                category = "bonus"
            else:
                category = "emerging"
            skills.append(
                SkillInsight(
                    name=stats["name"],
                    count=stats["count"],
                    percentage=_round(percentage),
                    required_count=stats["required"],
                    preferred_count=stats["preferred"],
                    category=category,
                    job_ids=stats["jobs"][:20],
                )
            )
        skills.sort(key=lambda item: (item.count, item.required_count), reverse=True)

        theme_data: dict[str, dict[str, Any]] = {}
        for job in jobs:
            structured = (job.normalized_data or {}).get("structured_job", {})
            responsibilities = structured.get("responsibilities") or []
            if not responsibilities:
                requirements = (job.normalized_data or {}).get("requirements", {})
                responsibilities = requirements.get("responsibilities") or []
            if not responsibilities:
                responsibilities = [
                    line.strip() for line in job.description.splitlines() if line.strip()
                ][:8]
            matched_names: set[str] = set()
            for responsibility in responsibilities:
                lowered = responsibility.lower()
                for name, keywords in THEMES:
                    if name not in matched_names and any(
                        keyword in lowered for keyword in keywords
                    ):
                        data = theme_data.setdefault(name, {"count": 0, "examples": [], "jobs": []})
                        data["count"] += 1
                        data["jobs"].append(job.id)
                        if len(data["examples"]) < 3:
                            data["examples"].append(responsibility[:160])
                        matched_names.add(name)
        themes = [
            ResponsibilityTheme(
                name=name,
                count=data["count"],
                percentage=_round(data["count"] / max(1, sample_count) * 100),
                examples=data["examples"],
                job_ids=data["jobs"][:20],
            )
            for name, data in theme_data.items()
        ]
        themes.sort(key=lambda item: item.count, reverse=True)

        clusters: dict[str, list[str]] = defaultdict(list)
        for job in jobs:
            structured = (job.normalized_data or {}).get("structured_job", {})
            role = str(structured.get("role_category") or "").strip() or self._cluster_title(
                job.title
            )
            clusters[role].append(job.title)
        role_clusters = [
            RoleCluster(
                name=name,
                count=len(titles),
                percentage=_round(len(titles) / max(1, sample_count) * 100),
                titles=list(dict.fromkeys(titles))[:5],
            )
            for name, titles in sorted(
                clusters.items(), key=lambda item: len(item[1]), reverse=True
            )
        ]

        roadmap = self._roadmap(query, skills)
        sources = [
            EvidenceJob(
                id=job.id,
                title=job.title,
                company=(
                    job.company.name
                    if job.company
                    else str((job.raw_data or {}).get("company_name") or "").strip() or None
                ),
                location=job.location,
                salary_text=_salary_text(job),
                education=job.education_requirement,
                experience=job.experience_requirement,
                source_url=job.source_url,
                relevance=_round(score),
            )
            for job, score in ranked_jobs[:20]
        ]
        education = _distribution([_education(job.education_requirement) for job in jobs])
        experience = _distribution([_experience(job.experience_requirement) for job in jobs])
        summary = self._summary(
            query, sample_count, confidence, salary_bands, education, skills, themes
        )
        data_as_of = max((job.updated_at for job in jobs), default=None)
        return MarketInsightResult(
            query=query,
            generated_at=_now(),
            data_as_of=data_as_of,
            sample_count=sample_count,
            confidence=confidence,
            warnings=warnings,
            salary_bands=salary_bands,
            education_distribution=education,
            experience_distribution=experience,
            skills=skills[:30],
            responsibility_themes=themes[:10],
            role_clusters=role_clusters[:10],
            learning_roadmap=roadmap,
            summary_markdown=summary,
            source_jobs=sources,
        )

    @staticmethod
    def _cluster_title(title: str) -> str:
        for keyword, label in (
            ("机器人", "机器人/控制"),
            ("算法", "算法"),
            ("agent", "AI Agent"),
            ("大模型", "大模型"),
            ("前端", "前端"),
            ("后端", "后端"),
            ("数据", "数据"),
        ):
            if keyword in title.lower():
                return label
        return title[:30]

    @staticmethod
    def _roadmap(query: str, skills: list[SkillInsight]) -> list[LearningPhase]:
        names = [item.name for item in skills]
        core = names[:4] or [query]
        next_skills = names[4:8] or core
        return [
            LearningPhase(
                weeks="第 1-2 周",
                title="基础与岗位认知",
                objectives=[f"建立 {query} 的知识框架", "复盘样本岗位共同要求"],
                skills=core[:3],
                deliverables=["岗位能力矩阵", "基础知识笔记与最小练习"],
                success_criteria=["能解释核心概念并完成基础代码练习"],
            ),
            LearningPhase(
                weeks="第 3-5 周",
                title="核心技能专项",
                objectives=["完成高频技能的系统训练", "形成可复用代码模块"],
                skills=(core + next_skills)[:6],
                deliverables=["2 个专项实验", "带测试的核心模块"],
                success_criteria=["能独立定位问题并解释方案取舍"],
            ),
            LearningPhase(
                weeks="第 6-8 周",
                title="岗位型项目",
                objectives=["按真实 JD 职责完成端到端项目", "记录数据、指标和迭代过程"],
                skills=next_skills[:4],
                deliverables=["一个可演示项目", "README、架构图和实验报告"],
                success_criteria=["项目可复现，核心指标和个人贡献清晰"],
            ),
            LearningPhase(
                weeks="第 9-10 周",
                title="工程化与质量",
                objectives=["补齐部署、性能、测试和协作能力"],
                skills=["测试", "工程化", "部署", *names[8:10]],
                deliverables=["自动化测试与部署脚本", "性能或质量改进记录"],
                success_criteria=["项目能稳定运行并有可验证质量指标"],
            ),
            LearningPhase(
                weeks="第 11-12 周",
                title="作品集与面试验证",
                objectives=["将经历映射到岗位要求", "进行针对性面试训练"],
                skills=core[:4],
                deliverables=["项目型简历", "作品集页面", "面试问题清单"],
                success_criteria=["每项核心要求都有项目证据或学习计划"],
            ),
        ]

    @staticmethod
    def _summary(
        query: str,
        sample_count: int,
        confidence: str,
        salaries: list[SalaryBand],
        education: list[DistributionItem],
        skills: list[SkillInsight],
        themes: list[ResponsibilityTheme],
    ) -> str:
        salary = (
            "、".join(
                f"{item.median:g}{item.unit_label}（P25–P75：{item.p25:g}–{item.p75:g}）"
                for item in salaries[:2]
            )
            or "样本不足"
        )
        education_text = education[0].label if education else "未注明"
        skill_text = "、".join(item.name for item in skills[:8]) or "尚未提取"
        theme_text = "、".join(item.name for item in themes[:4]) or "尚未形成稳定主题"
        return (
            f"# {query} 岗位市场洞察\n\n"
            f"本报告分析了 **{sample_count}** 条系统内相关岗位，置信度为 **{confidence}**。\n\n"
            f"- 薪资中位区间：{salary}\n"
            f"- 最常见学历要求：{education_text}\n"
            f"- 高频技能：{skill_text}\n"
            f"- 典型职责：{theme_text}\n\n"
            "建议先补齐高频必备技能，再用一个贴近真实职责的端到端项目形成可验证作品。"
        )


class MarketInsightService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = MarketInsightRepository(session)

    async def list(self) -> tuple[list[MarketInsightReport], int]:
        return await self.repository.list_reports()

    async def get(self, report_id: UUID) -> MarketInsightReport:
        report = await self.repository.get_report(report_id)
        if report is None:
            raise MarketInsightNotFoundError("职业洞察报告不存在")
        return report

    async def create(self, payload: MarketInsightCreate) -> tuple[MarketInsightReport, bool]:
        user = await self._default_user()
        watermark = await self.repository.data_watermark()
        request_data = payload.model_dump(mode="json", exclude={"force"})
        request_data["query"] = payload.query.strip()
        if payload.mode == "llm":
            provider = await LLMSettingsService(self.session).get_runtime_provider()
            request_data["llm_profile"] = {
                "provider": getattr(provider, "provider_name", "mock"),
                "model": getattr(provider, "model", "default"),
                "prompt_version": MARKET_INSIGHT_PROMPT_VERSION,
                "max_tokens": MARKET_INSIGHT_LLM_MAX_TOKENS,
            }
        fingerprint = hashlib.sha256(
            json.dumps(
                [MARKET_INSIGHT_VERSION, request_data, watermark],
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if not payload.force:
            cached = await self.repository.find_cached(fingerprint)
            if cached is not None:
                return cached, True
            active = await self.repository.find_active(fingerprint)
            if active is not None:
                return active, True
        report = MarketInsightReport(
            user_id=user.id,
            query=payload.query.strip(),
            mode=payload.mode,
            fingerprint=fingerprint,
            request_payload=request_data,
        )
        self.session.add(report)
        await self.session.commit()
        await self.session.refresh(report)
        return report, False

    async def execute(self, report_id: UUID, provider: LLMProvider) -> MarketInsightReport:
        report = await self.get(report_id)
        if report.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return report
        report.status = "RUNNING"
        report.stage = "searching_jobs"
        report.progress = 10
        report.started_at = report.started_at or _now()
        report.error = None
        await self.session.commit()
        try:
            payload = MarketInsightCreate.model_validate(report.request_payload)
            jobs = await self.repository.candidate_jobs(
                cities=payload.cities, job_types=payload.job_types
            )
            terms = _query_terms(payload.query)
            ranked = [(job, _relevance(job, payload.query, terms)) for job in jobs]
            ranked = [(job, score) for job, score in ranked if score >= 2.0]
            ranked.sort(key=lambda item: (item[1], item[0].updated_at), reverse=True)
            ranked = ranked[: payload.max_jobs]

            report.stage = "aggregating"
            report.progress = 45
            report.sample_count = len(ranked)
            report.source_job_ids = [str(job.id) for job, _ in ranked]
            await self.session.commit()

            result = MarketInsightAggregator().build(payload.query, ranked)
            report.report_payload = result.model_dump(mode="json")
            report.confidence = result.confidence
            report.progress = 78
            report.stage = "llm_summary" if payload.mode == "llm" else "saving"
            await self.session.commit()

            if payload.mode == "llm":
                result = await self._enhance_with_llm(result, provider)
                report.report_payload = result.model_dump(mode="json")
                report.llm_source = result.llm_source
                await self.session.commit()

            report.status = "SUCCEEDED"
            report.stage = "completed"
            report.progress = 100
            report.completed_at = _now()
            await self.session.commit()
            await self.session.refresh(report)
            return report
        except asyncio.CancelledError:
            await self.session.rollback()
            current = await self.get(report_id)
            if current.status != "CANCELLED":
                current.status = "CANCELLED"
                current.stage = "cancelled"
                current.completed_at = _now()
                await self.session.commit()
            raise
        except Exception as exc:
            await self.session.rollback()
            failed = await self.get(report_id)
            failed.status = "FAILED"
            failed.stage = "failed"
            failed.error = str(exc)[:1000] or "生成职业洞察失败"
            failed.completed_at = _now()
            await self.session.commit()
            return failed

    async def cancel(self, report_id: UUID) -> MarketInsightReport:
        report = await self.get(report_id)
        if report.status in {"PENDING", "RUNNING"}:
            report.status = "CANCELLED"
            report.stage = "cancelled"
            report.error = "任务已由用户取消。"
            report.completed_at = _now()
            await self.session.commit()
        return report

    async def retry(self, report_id: UUID) -> MarketInsightReport:
        report = await self.get(report_id)
        if report.status not in {"FAILED", "CANCELLED"}:
            raise MarketInsightActionError("只有失败或已取消的报告可以重试")
        report.status = "PENDING"
        report.stage = "queued"
        report.progress = 0
        report.error = None
        report.started_at = None
        report.completed_at = None
        await self.session.commit()
        return report

    async def delete(self, report_id: UUID) -> None:
        report = await self.get(report_id)
        if report.status in {"PENDING", "RUNNING"}:
            raise MarketInsightActionError("请先取消正在运行的报告")
        await self.session.execute(
            delete(MarketInsightReport).where(MarketInsightReport.id == report.id)
        )
        await self.session.commit()

    async def _default_user(self) -> User:
        settings = get_settings()
        user = await self.session.scalar(
            select(User).where(User.email == settings.default_user_email)
        )
        if user is None:
            user = User(email=settings.default_user_email, name=settings.default_user_name)
            self.session.add(user)
            await self.session.flush()
        return user

    @staticmethod
    async def _enhance_with_llm(
        result: MarketInsightResult, provider: LLMProvider
    ) -> MarketInsightResult:
        if getattr(provider, "provider_name", "mock") == "mock" or result.sample_count < 5:
            result.llm_source = "deterministic_fallback"
            result.warnings.append("深度模式未调用远程 LLM，已保留确定性统计与学习路线。")
            return result
        compact = _llm_digest(result)
        prompt = (
            "你是职业研究顾问。直接根据下面的聚合统计返回精简 JSON，不展示推理过程。"
            "不得重新计算、改写或虚构统计数字。summary_markdown 控制在 500 个中文字符内；"
            "learning_priorities 最多 5 条；roadmap_adjustments 只填写确有必要调整的阶段，"
            "不得重写完整路线。\n" + json.dumps(compact, ensure_ascii=False)
        )
        try:
            enhanced = await provider.generate_structured(
                prompt,
                MarketInsightLLMOutput,
                max_tokens=MARKET_INSIGHT_LLM_MAX_TOKENS,
            )
            if enhanced.summary_markdown.strip():
                result.summary_markdown = enhanced.summary_markdown.strip()
            priorities = [item.strip() for item in enhanced.learning_priorities if item.strip()]
            if priorities:
                result.summary_markdown += "\n\n## 学习优先级\n\n" + "\n".join(
                    f"- {item}" for item in priorities
                )
            phases = {phase.weeks: phase for phase in result.learning_roadmap}
            for adjustment in enhanced.roadmap_adjustments:
                phase = phases.get(adjustment.weeks.strip())
                if phase is None:
                    continue
                focus = adjustment.focus.strip()
                if focus and focus not in phase.objectives:
                    phase.objectives.append(focus)
                phase.skills = list(
                    dict.fromkeys(
                        [*phase.skills, *(item.strip() for item in adjustment.add_skills)]
                    )
                )[:8]
            result.llm_source = getattr(provider, "provider_name", "llm")
        except Exception:
            result.llm_source = "deterministic_fallback"
            result.warnings.append("LLM 深度总结失败，已自动回退到确定性报告。")
        return result


_active_market_tasks: dict[UUID, asyncio.Task[None]] = {}


async def execute_market_insight(report_id: UUID) -> None:
    async with SessionLocal() as session:
        provider = await LLMSettingsService(session).get_runtime_provider()
        await MarketInsightService(session).execute(report_id, provider)


def schedule_market_insight(report_id: UUID) -> None:
    existing = _active_market_tasks.get(report_id)
    if existing and not existing.done():
        return

    async def runner() -> None:
        try:
            await execute_market_insight(report_id)
        finally:
            _active_market_tasks.pop(report_id, None)

    _active_market_tasks[report_id] = asyncio.create_task(runner())


async def stop_market_insight(report_id: UUID) -> None:
    task = _active_market_tasks.get(report_id)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def recover_interrupted_market_insights() -> list[UUID]:
    async with SessionLocal() as session:
        reports = list(
            (
                await session.scalars(
                    select(MarketInsightReport).where(
                        MarketInsightReport.status.in_(["PENDING", "RUNNING"])
                    )
                )
            ).all()
        )
        for report in reports:
            report.status = "PENDING"
            report.stage = "queued"
            report.error = None
        await session.commit()
        return [report.id for report in reports]


async def shutdown_market_insight_tasks() -> None:
    tasks = list(_active_market_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_market_tasks.clear()
