"""Typed public contracts for Career Advisor Agent Runtime tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.knowledge_search import JobKnowledgeStatistics


class _StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchJobsToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="要在系统已持久化岗位中检索的职位名称、方向或关键词。",
    )
    limit: int = Field(default=30, ge=1, le=50, description="最多返回的岗位数量。")


class CollectJobsOnlineToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=160,
        description=(
            "根据用户明确目标、聊天上下文和简历技能/项目/经历综合生成的具体岗位搜索短语；"
            "建议 2-6 个关键词。不得包含操作指令、平台、城市或数量，不得只填‘后端’、"
            "‘开发’、‘实习’等宽泛词。"
        ),
    )
    platform: Literal["boss", "zhaopin", "auto"] = Field(
        default="auto",
        description="招聘平台：boss 为 BOSS 直聘，zhaopin 为智联招聘。",
    )
    city: str = Field(default="北京", min_length=1, max_length=40, description="搜索城市。")
    max_jobs: int = Field(default=20, ge=1, le=200, description="本次最多采集岗位数。")
    quick_score_threshold: float = Field(
        default=60,
        ge=0,
        le=100,
        description="快速评分阈值；低于阈值的岗位默认不勾选。",
    )


class SearchJobKnowledgeToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="需要岗位知识库用 JD 证据回答的问题或检索主题。",
    )


class AggregateJobMarketToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="需要统计薪资、学历、经验或技能分布的岗位方向。",
    )


class ExplainSkillDemandToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="需要分析企业技能需求的岗位方向或具体技能问题。",
    )


class BuildLearningRoadmapToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="用户希望学习的岗位方向、技能目标和时间约束。",
    )


class AnalyzeResumeGapToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="要与当前会话绑定简历比较的目标岗位或能力问题。",
    )


class CompareRoleProfilesToolInput(_StrictToolInput):
    queries: list[str] = Field(
        min_length=2,
        max_length=2,
        description="需要对比的两个岗位方向，必须恰好提供两项。",
    )


class RecommendJobsToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="需要结合岗位知识和当前简历推荐的职位条件。",
    )


class DeepDiveSkillRequirementsToolInput(_StrictToolInput):
    query: str = Field(
        min_length=1,
        max_length=300,
        description="需要进一步检索 JD 职责和任职要求的岗位方向。",
    )
    skills: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="需要深挖的重点技能；留空时由已有岗位统计自动选择。",
    )


class RetrieveCareerMemoryToolInput(_StrictToolInput):
    query: str = Field(min_length=1, max_length=300, description="记忆检索主题。")
    memory_types: list[str] = Field(
        default_factory=list,
        max_length=7,
        description="允许读取的职业记忆类型。",
    )
    memory_keys: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="允许读取的精确记忆键。",
    )
    limit: int = Field(default=6, ge=0, le=20, description="最多返回的记忆条数。")
    token_budget: int = Field(
        default=700,
        ge=100,
        le=4000,
        description="注入对话上下文的最大 token 预算。",
    )


class EvidenceToolOutput(BaseModel):
    sample_count: int = Field(ge=0, description="命中的岗位样本数。")
    citation_count: int = Field(ge=0, description="可用于回答的证据引用数。")
    warnings: list[str] = Field(default_factory=list, description="数据质量或降级提示。")
    cache_hit: bool | None = Field(default=None, description="是否命中检索缓存。")


class SearchJobsToolOutput(BaseModel):
    count: int = Field(ge=0, description="检索到的岗位数。")
    selected_count: int = Field(ge=0, description="默认选中的高匹配岗位数。")
    low_match_count: int = Field(ge=0, description="低于快速评分阈值的岗位数。")
    expired_count: int = Field(ge=0, description="超过自动投递时效的岗位数。")


class CollectJobsOnlineToolOutput(BaseModel):
    action_type: Literal["job_collection_request"]
    platform: Literal["boss", "zhaopin"]
    query: str
    city: str
    target_count: int = Field(ge=1, le=200)
    quick_score_threshold: float = Field(ge=0, le=100)
    result_source: Literal["automated_collection"]


class ResumeGapToolOutput(EvidenceToolOutput):
    resume_id: str | None = None
    resume_name: str | None = None
    covered_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    coverage_percentage: float | None = Field(default=None, ge=0, le=100)


class LearningRoadmapToolOutput(EvidenceToolOutput):
    roadmap: list[dict[str, Any]] = Field(
        default_factory=list,
        description="按阶段生成的学习目标、技能和交付物。",
    )


class SkillDemandToolOutput(EvidenceToolOutput):
    skills: list[str] = Field(default_factory=list, description="岗位中的重点技能名称。")


class RoleComparisonToolOutput(BaseModel):
    reports: list[dict[str, Any]] = Field(
        default_factory=list,
        description="两个岗位方向各自的样本量、引用数和数据提示。",
    )


class SkillDeepDiveToolOutput(BaseModel):
    skills: list[dict[str, Any]] = Field(
        default_factory=list,
        description="按技能整理的 JD 深挖检索摘要。",
    )


class CareerMemoryToolOutput(BaseModel):
    count: int = Field(ge=0, description="实际注入的职业记忆条数。")
    memory_types: list[str] = Field(default_factory=list)
    memory_keys: list[str] = Field(default_factory=list)
    token_budget: int = Field(ge=0)


CAREER_ADVISOR_TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "search_jobs": SearchJobsToolInput,
    "collect_jobs_online": CollectJobsOnlineToolInput,
    "search_job_knowledge": SearchJobKnowledgeToolInput,
    "retrieve_career_memory": RetrieveCareerMemoryToolInput,
    "aggregate_job_market": AggregateJobMarketToolInput,
    "explain_skill_demand": ExplainSkillDemandToolInput,
    "build_learning_roadmap": BuildLearningRoadmapToolInput,
    "analyze_resume_gap": AnalyzeResumeGapToolInput,
    "compare_role_profiles": CompareRoleProfilesToolInput,
    "recommend_jobs": RecommendJobsToolInput,
    "deep_dive_skill_requirements": DeepDiveSkillRequirementsToolInput,
}

CAREER_ADVISOR_TOOL_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "search_jobs": SearchJobsToolOutput,
    "collect_jobs_online": CollectJobsOnlineToolOutput,
    "search_job_knowledge": EvidenceToolOutput,
    "retrieve_career_memory": CareerMemoryToolOutput,
    "aggregate_job_market": JobKnowledgeStatistics,
    "explain_skill_demand": SkillDemandToolOutput,
    "build_learning_roadmap": LearningRoadmapToolOutput,
    "analyze_resume_gap": ResumeGapToolOutput,
    "compare_role_profiles": RoleComparisonToolOutput,
    "recommend_jobs": EvidenceToolOutput,
    "deep_dive_skill_requirements": SkillDeepDiveToolOutput,
}
