"""Deterministic guardrails around Agent tool calls.

The LLM (or the current deterministic planner) may propose a tool call, but
this module owns the decision to expose, validate, authorize and verify it.
It intentionally stores no database state; callers persist the returned trace
and history in their existing AgentRun checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError


class ToolRiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ToolExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    REJECTED = "REJECTED"


class ToolSemanticStatus(StrEnum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class RecoveryAction(StrEnum):
    RETRY = "RETRY"
    REPAIR_ARGUMENTS = "REPAIR_ARGUMENTS"
    SWITCH_TOOL = "SWITCH_TOOL"
    REFORMULATE_QUERY = "REFORMULATE_QUERY"
    REPLAN = "REPLAN"
    ASK_USER = "ASK_USER"
    ABORT = "ABORT"


class GovernancePhase(StrEnum):
    UNDERSTAND = "UNDERSTAND"
    PLAN = "PLAN"
    SEARCH = "SEARCH"
    RETRIEVE = "RETRIEVE"
    ANALYZE = "ANALYZE"
    GENERATE = "GENERATE"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class ToolManifest:
    name: str
    description: str
    capabilities: tuple[str, ...] = ()
    suitable_for: tuple[str, ...] = ()
    unsuitable_for: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: ToolRiskLevel = ToolRiskLevel.LOW
    cost_level: str = "LOW"
    latency_level: str = "LOW"
    requires_confirmation: bool = False
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    allowed_states: tuple[str, ...] = (GovernancePhase.ANALYZE.value,)
    tags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "suitable_for": list(self.suitable_for),
            "unsuitable_for": list(self.unsuitable_for),
            "input_schema": self.input_schema,
            "risk_level": self.risk_level.value,
            "cost_level": self.cost_level,
            "latency_level": self.latency_level,
            "requires_confirmation": self.requires_confirmation,
            "preconditions": list(self.preconditions),
            "postconditions": list(self.postconditions),
            "allowed_states": list(self.allowed_states),
            "tags": list(self.tags),
        }


def _career_advisor_manifest(
    name: str,
    description: str,
    *,
    capabilities: tuple[str, ...],
    suitable_for: tuple[str, ...],
    allowed_states: tuple[str, ...],
    cost_level: str = "LOW",
    latency_level: str = "MEDIUM",
    tags: tuple[str, ...] = ("read", "knowledge-base"),
) -> ToolManifest:
    """Manifests for Career Advisor tools and typed UI handoffs.

    Keeping these beside the generic Agent manifests makes the governance
    layer independent from either caller. External actions are represented as
    explicit, auditable UI handoffs and run in a visible user browser.
    """

    return ToolManifest(
        name=name,
        description=description,
        capabilities=capabilities,
        suitable_for=suitable_for,
        allowed_states=allowed_states,
        cost_level=cost_level,
        latency_level=latency_level,
        tags=tags,
    )


CAREER_ADVISOR_TOOL_MANIFESTS: dict[str, ToolManifest] = {
    "search_jobs": _career_advisor_manifest(
        "search_jobs",
        "检索系统中已经持久化的具体岗位，并返回可查看、筛选和准备投递的岗位卡片；"
        "适合用户要求查找系统现有岗位，不用于联网采集。",
        capabilities=("job_search", "local_database_search", "job_recommendation"),
        suitable_for=("job_recommendation", "market_research"),
        allowed_states=(GovernancePhase.SEARCH.value,),
        latency_level="MEDIUM",
        tags=("read", "retrieval", "interactive-card"),
    ),
    "collect_jobs_online": _career_advisor_manifest(
        "collect_jobs_online",
        "通过 CareerPilot 浏览器扩展在 BOSS 直聘或智联招聘搜索岗位；"
        "在聊天内创建可操作卡片，并逐步采集、持久化完整 JD 和快速评分。"
        "用户明确要求在招聘网站搜索、采集或爬取岗位时调用。",
        capabilities=(
            "job_search",
            "external_job_collection",
            "browser_automation",
            "job_recommendation",
        ),
        suitable_for=("job_recommendation", "market_research"),
        allowed_states=(GovernancePhase.SEARCH.value,),
        cost_level="MEDIUM",
        latency_level="HIGH",
        tags=("interactive-card", "external", "user-visible", "persisted-results"),
    ),
    "search_job_knowledge": _career_advisor_manifest(
        "search_job_knowledge",
        "从岗位知识库检索可追溯的 JD 证据；适合回答岗位要求、职责、学历、经验和技能问题。",
        capabilities=("job_knowledge_search", "local_database_search", "evidence_retrieval"),
        suitable_for=("market_research", "salary_analysis", "skill_analysis"),
        allowed_states=(GovernancePhase.SEARCH.value, GovernancePhase.RETRIEVE.value),
        latency_level="HIGH",
    ),
    "retrieve_career_memory": _career_advisor_manifest(
        "retrieve_career_memory",
        "在明确的类型、键和 token 限制内读取用户已确认的职业偏好与长期记忆。",
        capabilities=("memory_retrieval", "private_data_read", "read_only"),
        suitable_for=("learning_roadmap", "resume_gap", "job_recommendation", "follow_up"),
        allowed_states=(GovernancePhase.RETRIEVE.value,),
        latency_level="LOW",
        tags=("read", "private", "memory"),
    ),
    "aggregate_job_market": _career_advisor_manifest(
        "aggregate_job_market",
        "聚合相关岗位的薪资、学历、经验和技能分布；适合市场行情与薪资分析。",
        capabilities=("market_analysis", "job_knowledge_search", "statistics"),
        suitable_for=("market_research", "salary_analysis"),
        allowed_states=(GovernancePhase.ANALYZE.value,),
    ),
    "explain_skill_demand": _career_advisor_manifest(
        "explain_skill_demand",
        "依据标准化岗位证据解释技能需求、出现频率、必备程度和典型工作场景。",
        capabilities=("skill_analysis", "job_knowledge_search", "evidence_retrieval"),
        suitable_for=("skill_analysis",),
        allowed_states=(GovernancePhase.ANALYZE.value,),
    ),
    "build_learning_roadmap": _career_advisor_manifest(
        "build_learning_roadmap",
        "根据目标岗位需求构建可执行学习路线；仅在用户要求学习规划或准备路径时使用。",
        capabilities=("learning_plan", "job_knowledge_search", "evidence_retrieval"),
        suitable_for=("learning_roadmap",),
        allowed_states=(GovernancePhase.ANALYZE.value,),
        cost_level="MEDIUM",
        latency_level="HIGH",
    ),
    "analyze_resume_gap": _career_advisor_manifest(
        "analyze_resume_gap",
        "将当前会话绑定的私有简历与目标岗位证据比较，识别已覆盖能力和关键差距。",
        capabilities=("resume_matching", "private_data_read", "job_knowledge_search"),
        suitable_for=("resume_gap",),
        allowed_states=(GovernancePhase.ANALYZE.value,),
        tags=("read", "private", "knowledge-base"),
    ),
    "compare_role_profiles": _career_advisor_manifest(
        "compare_role_profiles",
        "使用相同证据口径比较恰好两个岗位方向，包括岗位量、要求和能力侧重点。",
        capabilities=("role_comparison", "job_knowledge_search", "evidence_retrieval"),
        suitable_for=("role_comparison",),
        allowed_states=(GovernancePhase.ANALYZE.value,),
        latency_level="HIGH",
    ),
    "recommend_jobs": _career_advisor_manifest(
        "recommend_jobs",
        "依据岗位知识库和可选简历推荐岗位；用于分析型推荐，不负责联网采集。",
        capabilities=("job_recommendation", "resume_matching", "job_knowledge_search"),
        suitable_for=("job_recommendation",),
        allowed_states=(GovernancePhase.SEARCH.value, GovernancePhase.ANALYZE.value),
        latency_level="HIGH",
        tags=("read", "private", "knowledge-base"),
    ),
    "deep_dive_skill_requirements": _career_advisor_manifest(
        "deep_dive_skill_requirements",
        "针对已有高频技能继续检索有限数量的 JD 职责与任职要求，补充可验证能力标准。",
        capabilities=("skill_analysis", "jd_deep_retrieval", "evidence_retrieval"),
        suitable_for=("learning_roadmap", "skill_analysis", "resume_gap"),
        allowed_states=(GovernancePhase.RETRIEVE.value, GovernancePhase.ANALYZE.value),
        cost_level="MEDIUM",
        latency_level="HIGH",
    ),
}


@dataclass(frozen=True)
class ToolNeedDecision:
    need_tool: bool
    reason: str
    confidence: float
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolMatch:
    tool_name: str
    confidence: float
    capability_overlap: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    schema_valid: bool = False
    semantic_valid: bool = False
    policy_valid: bool = False
    permission_valid: bool = False
    preconditions_valid: bool = False
    duplicate_valid: bool = False
    budget_valid: bool = False
    reason: str | None = None
    normalized_arguments: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "schema": self.schema_valid,
            "semantic": self.semantic_valid,
            "policy": self.policy_valid,
            "permission": self.permission_valid,
            "preconditions": self.preconditions_valid,
            "duplicate": self.duplicate_valid,
            "budget": self.budget_valid,
            "reason": self.reason,
            "normalized_arguments": self.normalized_arguments,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ToolExecutionResult:
    execution_status: ToolExecutionStatus
    semantic_status: ToolSemanticStatus
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    confidence: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_status", ToolExecutionStatus(self.execution_status))
        object.__setattr__(self, "semantic_status", ToolSemanticStatus(self.semantic_status))

    def as_dict(self) -> dict[str, Any]:
        return {
            "execution_status": self.execution_status.value,
            "semantic_status": self.semantic_status.value,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "latency_ms": self.latency_ms,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ResultVerification:
    valid: bool
    semantic_status: ToolSemanticStatus
    relevance_score: float
    constraint_satisfaction: dict[str, bool] = field(default_factory=dict)
    reason: str | None = None
    confidence: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "semantic_status": self.semantic_status.value,
            "relevance_score": self.relevance_score,
            "constraint_satisfaction": self.constraint_satisfaction,
            "reason": self.reason,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class GoalVerification:
    goal_completed: bool
    missing_requirements: tuple[str, ...] = ()
    confidence: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal_completed": self.goal_completed,
            "missing_requirements": list(self.missing_requirements),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    reason: str | None = None
    requires_confirmation: bool = False


class ToolNeedClassifier:
    """Cheap first gate; it never calls an LLM."""

    _tool_signals = re.compile(
        r"搜索|查询|检索|查找|岗位|职位|简历|投递|排名|计算|统计|最新|今天|实时|导入|创建|删除|修改|发送|文件|目录|项目文件|代码库|仓库|调用工具",
        re.I,
    )

    def classify(self, goal: str) -> ToolNeedDecision:
        if not goal.strip():
            return ToolNeedDecision(False, "empty goal", 1.0)
        if self._tool_signals.search(goal):
            capabilities = []
            if re.search(r"岗位|职位|投递|招聘", goal, re.I):
                capabilities.append("job_search")
            if re.search(r"简历|匹配|排名", goal, re.I):
                capabilities.append("resume_matching")
            if re.search(r"我的简历|个人资料|私有数据", goal, re.I):
                capabilities.append("private_data_read")
            if re.search(r"最新|今天|实时", goal, re.I):
                capabilities.append("realtime_information")
            if re.search(r"文件|目录|项目文件|代码库|仓库", goal, re.I):
                capabilities.append("project_file_access")
            if re.search(r"计算|求和|百分比|统计", goal, re.I):
                capabilities.append("computation")
            if re.search(r"投递|发送|删除|修改|创建", goal, re.I):
                capabilities.append("external_side_effect")
            return ToolNeedDecision(
                True,
                "goal contains an operation, private-data, or freshness signal",
                0.92,
                tuple(dict.fromkeys(capabilities)),
            )
        return ToolNeedDecision(False, "general knowledge can be answered without a tool", 0.78)


class CapabilityMatcher:
    def match(
        self,
        required_capabilities: list[str] | tuple[str, ...],
        available_tools: list[ToolManifest],
    ) -> list[ToolMatch]:
        required = {item.strip().casefold() for item in required_capabilities if item.strip()}
        matches: list[ToolMatch] = []
        for tool in available_tools:
            capabilities = {item.casefold() for item in tool.capabilities}
            overlap = len(required & capabilities) / max(len(required), 1)
            suitable = len({item.casefold() for item in tool.suitable_for} & required) / max(
                len(required), 1
            )
            confidence = min(1.0, 0.70 * overlap + 0.20 * suitable + 0.10)
            reasons = []
            if overlap:
                reasons.append("capability overlap")
            if suitable:
                reasons.append("suitable-for match")
            if not reasons:
                reasons.append("no explicit capability match")
            matches.append(
                ToolMatch(tool.name, round(confidence, 4), round(overlap, 4), tuple(reasons))
            )
        return sorted(matches, key=lambda item: item.confidence, reverse=True)


class ToolExposureManager:
    def get_allowed_tools(
        self,
        phase: str,
        manifests: list[ToolManifest],
    ) -> list[ToolManifest]:
        return [tool for tool in manifests if phase in tool.allowed_states]

    def is_allowed(self, phase: str, manifest: ToolManifest) -> bool:
        return phase in manifest.allowed_states


class SemanticValidator:
    def validate(self, tool_name: str, payload: dict[str, Any]) -> tuple[bool, str | None]:
        errors: list[str] = []
        for field_name in ("keywords", "cities", "platforms"):
            values = payload.get(field_name)
            if isinstance(values, list) and any(not str(value).strip() for value in values):
                errors.append(f"{field_name} contains a blank value")
        for field_name in ("query", "name", "prompt"):
            value = payload.get(field_name)
            if value is not None and isinstance(value, str) and not value.strip():
                errors.append(f"{field_name} must not be blank")
        if payload.get("salary_min") is not None and payload.get("salary_max") is not None:
            if payload["salary_min"] > payload["salary_max"]:
                errors.append("salary_min must not exceed salary_max")
        if payload.get("date_from") and payload.get("date_to"):
            if str(payload["date_from"]) > str(payload["date_to"]):
                errors.append("date_from must not be after date_to")
        for field_name in ("job_ids", "selected_job_ids"):
            values = payload.get(field_name)
            if isinstance(values, list) and len(values) != len(set(map(str, values))):
                errors.append(f"{field_name} contains duplicate IDs")
        if tool_name == "search_jobs" and not any(
            payload.get(field_name) for field_name in ("keywords", "cities", "platforms")
        ):
            errors.append("search_jobs requires at least one search constraint")
        if tool_name == "collect_jobs_online":
            if not str(payload.get("query", "")).strip():
                errors.append("collect_jobs_online requires a non-blank query")
            if payload.get("platform") not in {"boss", "zhaopin", "auto"}:
                errors.append("collect_jobs_online platform must be boss, zhaopin, or auto")
            max_jobs = payload.get("max_jobs")
            if not isinstance(max_jobs, int) or not 1 <= max_jobs <= 200:
                errors.append("collect_jobs_online max_jobs must be between 1 and 200")
            threshold = payload.get("quick_score_threshold")
            if not isinstance(threshold, int | float) or not 0 <= threshold <= 100:
                errors.append("collect_jobs_online quick_score_threshold must be between 0 and 100")
        if tool_name == "queue_application" and not payload.get("job_ids"):
            errors.append("queue_application requires at least one job")
        # ``search_jobs`` is shared with the job-search orchestrator and uses
        # keywords/cities/platforms instead of a free-form query. Validate its
        # own contract above rather than applying the advisor query contract.
        if (
            tool_name in CAREER_ADVISOR_TOOL_MANIFESTS
            and tool_name not in {"search_jobs", "collect_jobs_online"}
            and not str(payload.get("query", "")).strip()
        ):
            errors.append(f"{tool_name} requires a non-blank query")
        if tool_name == "compare_role_profiles":
            queries = payload.get("queries")
            if not isinstance(queries, list) or len(queries) != 2:
                errors.append("compare_role_profiles requires exactly two queries")
        if tool_name == "deep_dive_skill_requirements":
            skills = payload.get("skills")
            if not isinstance(skills, list) or not skills:
                errors.append("deep_dive_skill_requirements requires at least one skill")
        return not errors, "; ".join(errors) if errors else None


class ToolPolicyEngine:
    def check(
        self,
        manifest: ToolManifest,
        *,
        phase: str,
        confirmation_granted: bool = False,
        explicit_authorization: bool = False,
        user_authorized: bool = True,
    ) -> ToolPolicyDecision:
        if not user_authorized:
            return ToolPolicyDecision(False, "user is not authorized for this Agent Run")
        if phase not in manifest.allowed_states:
            return ToolPolicyDecision(
                False,
                f"tool {manifest.name} is not exposed in phase {phase}",
            )
        if manifest.risk_level == ToolRiskLevel.CRITICAL and not explicit_authorization:
            return ToolPolicyDecision(False, "critical tools require explicit authorization")
        if manifest.requires_confirmation and not confirmation_granted:
            return ToolPolicyDecision(
                False,
                f"tool {manifest.name} requires user confirmation",
                requires_confirmation=True,
            )
        return ToolPolicyDecision(True)


class ToolCallHistory:
    @staticmethod
    def signature(tool_name: str, arguments: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"tool": tool_name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def contains(
        cls, history: list[dict[str, Any]], tool_name: str, arguments: dict[str, Any]
    ) -> bool:
        signature = cls.signature(tool_name, arguments)
        return any(item.get("signature") == signature for item in history)

    @classmethod
    def append(
        cls,
        history: list[dict[str, Any]],
        tool_name: str,
        arguments: dict[str, Any],
        *,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        updated = list(history)
        updated.append(
            {
                "signature": cls.signature(tool_name, arguments),
                "tool": tool_name,
                "arguments": arguments,
                "timestamp": datetime.now(UTC).isoformat(),
                "status": status,
                "result": result,
            }
        )
        return updated[-100:]


class ToolBudget:
    _cost_units = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 4.0, "CRITICAL": 8.0}

    def __init__(
        self,
        *,
        max_tool_calls: int,
        max_retry_per_tool: int = 2,
        max_search_calls: int | None = None,
        max_total_cost: float | None = None,
    ):
        self.max_tool_calls = max(1, max_tool_calls)
        self.max_retry_per_tool = max(0, max_retry_per_tool)
        self.max_search_calls = max_search_calls
        self.max_total_cost = max_total_cost

    def check(
        self,
        calls_used: int,
        *,
        search_calls_used: int = 0,
        total_cost: float = 0.0,
        tool_name: str | None = None,
        tool_cost_level: str = "LOW",
    ) -> tuple[bool, str | None]:
        if calls_used >= self.max_tool_calls:
            return False, f"tool budget exhausted ({self.max_tool_calls} calls)"
        if (
            tool_name in {"search_jobs", "collect_jobs_online"}
            and self.max_search_calls is not None
            and search_calls_used >= self.max_search_calls
        ):
            return False, f"search budget exhausted ({self.max_search_calls} calls)"
        projected_cost = total_cost + self._cost_units.get(tool_cost_level, 1.0)
        if self.max_total_cost is not None and projected_cost > self.max_total_cost:
            return False, f"tool cost budget exhausted ({self.max_total_cost} units)"
        return True, None


class ToolCallValidator:
    def __init__(
        self,
        *,
        semantic: SemanticValidator | None = None,
        policy: ToolPolicyEngine | None = None,
    ) -> None:
        self.semantic = semantic or SemanticValidator()
        self.policy = policy or ToolPolicyEngine()

    def validate(
        self,
        manifest: ToolManifest,
        input_schema: type[BaseModel],
        payload: dict[str, Any],
        *,
        phase: str,
        history: list[dict[str, Any]],
        calls_used: int,
        budget: ToolBudget,
        attempt: int = 1,
        confirmation_granted: bool = False,
        explicit_authorization: bool = False,
        user_authorized: bool = True,
        precondition_context: dict[str, bool] | None = None,
        search_calls_used: int = 0,
        total_cost: float = 0.0,
    ) -> ValidationResult:
        try:
            normalized = input_schema.model_validate(payload).model_dump(mode="json")
        except ValidationError as exc:
            return ValidationResult(
                False,
                reason=f"schema validation failed: {exc.errors()[0].get('msg', 'invalid input')}",
            )
        semantic_valid, semantic_reason = self.semantic.validate(manifest.name, normalized)
        policy = self.policy.check(
            manifest,
            phase=phase,
            confirmation_granted=confirmation_granted,
            explicit_authorization=explicit_authorization,
            user_authorized=user_authorized,
        )
        budget_valid, budget_reason = budget.check(
            calls_used,
            search_calls_used=search_calls_used,
            total_cost=total_cost,
            tool_name=manifest.name,
            tool_cost_level=manifest.cost_level,
        )
        precondition_context = precondition_context or {}
        missing_preconditions = [
            name for name in manifest.preconditions if not precondition_context.get(name, False)
        ]
        preconditions_valid = not missing_preconditions
        precondition_reason = (
            "missing preconditions: " + ", ".join(missing_preconditions)
            if missing_preconditions
            else None
        )
        duplicate_valid = attempt > 1 or not ToolCallHistory.contains(
            history, manifest.name, normalized
        )
        reason = (
            semantic_reason
            or policy.reason
            or budget_reason
            or precondition_reason
            or ("duplicate tool call" if not duplicate_valid else None)
        )
        return ValidationResult(
            valid=(
                semantic_valid
                and policy.allowed
                and budget_valid
                and preconditions_valid
                and duplicate_valid
            ),
            schema_valid=True,
            semantic_valid=semantic_valid,
            policy_valid=policy.allowed,
            permission_valid=policy.allowed,
            preconditions_valid=preconditions_valid,
            duplicate_valid=duplicate_valid,
            budget_valid=budget_valid,
            reason=reason,
            normalized_arguments=normalized,
            confidence=0.95 if policy.allowed else 0.0,
        )


class ToolResultVerifier:
    """Verify semantic usefulness after a tool has returned successfully."""

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> ResultVerification:
        if not isinstance(result, dict):
            return ResultVerification(
                False, ToolSemanticStatus.INVALID, 0.0, reason="result is not an object"
            )
        if tool_name == "search_jobs":
            count = int(result.get("count", 0) or 0)
            jobs = result.get("jobs")
            if isinstance(jobs, list):
                valid = count == len(jobs)
                return ResultVerification(
                    valid,
                    ToolSemanticStatus.VALID if valid and jobs else ToolSemanticStatus.PARTIAL,
                    0.9 if valid and jobs else 0.25,
                    reason=None if valid and jobs else "job search returned no candidates",
                )
            ids = result.get("job_ids", [])
            consistent = count == len(ids)
            if not consistent:
                return ResultVerification(
                    False, ToolSemanticStatus.INVALID, 0.1, reason="count and job_ids disagree"
                )
            if count == 0:
                return ResultVerification(
                    True, ToolSemanticStatus.PARTIAL, 0.25, reason="search returned no jobs"
                )
            return ResultVerification(
                True, ToolSemanticStatus.VALID, 0.9, {"has_results": True}, confidence=0.9
            )
        if tool_name == "collect_jobs_online":
            action = result.get("ui_action")
            valid = isinstance(action, dict) and action.get("type") == "job_collection_request"
            return ResultVerification(
                valid,
                ToolSemanticStatus.VALID if valid else ToolSemanticStatus.INVALID,
                0.95 if valid else 0.1,
                reason=None if valid else "online collection did not return a typed UI action",
            )
        if tool_name == "get_job":
            found = bool(result.get("found"))
            return ResultVerification(
                found,
                ToolSemanticStatus.VALID if found else ToolSemanticStatus.INVALID,
                0.95 if found else 0.1,
                reason=None if found else "job not found",
            )
        if tool_name == "retrieve_resume":
            valid = bool(result.get("resume_id")) and bool(result.get("name"))
            return ResultVerification(
                valid,
                ToolSemanticStatus.VALID if valid else ToolSemanticStatus.INVALID,
                0.95 if valid else 0.1,
                reason=None if valid else "resume profile is incomplete",
            )
        if tool_name == "rank_jobs":
            candidates = result.get("candidates", [])
            if int(result.get("count", 0) or 0) != len(candidates):
                return ResultVerification(
                    False,
                    ToolSemanticStatus.INVALID,
                    0.1,
                    reason="rank count and candidates disagree",
                )
            return ResultVerification(
                True,
                ToolSemanticStatus.VALID if candidates else ToolSemanticStatus.PARTIAL,
                0.9 if candidates else 0.3,
                reason=None if candidates else "no ranked candidates",
            )
        if tool_name == "score_job":
            score = result.get("final_score")
            valid = bool(result.get("job_id")) and isinstance(score, int | float)
            return ResultVerification(
                valid,
                ToolSemanticStatus.VALID if valid else ToolSemanticStatus.INVALID,
                0.9 if valid else 0.1,
                reason=None if valid else "single-job score result is incomplete",
            )
        if tool_name == "create_campaign":
            valid = bool(result.get("campaign_id")) and bool(result.get("status"))
            return ResultVerification(
                valid,
                ToolSemanticStatus.VALID if valid else ToolSemanticStatus.INVALID,
                0.9 if valid else 0.1,
                reason=None if valid else "campaign was not persisted",
            )
        if tool_name == "queue_application":
            valid = bool(result.get("campaign_id")) and int(result.get("queued_count", 0) or 0) >= 0
            return ResultVerification(
                valid,
                ToolSemanticStatus.VALID if valid else ToolSemanticStatus.INVALID,
                0.95 if valid else 0.1,
                reason=None if valid else "queue result is incomplete",
            )
        if tool_name == "retrieve_career_memory":
            count = result.get("count")
            try:
                valid = count is not None and int(count) >= 0
            except (TypeError, ValueError):
                valid = False
            return ResultVerification(
                valid,
                (
                    ToolSemanticStatus.VALID
                    if valid and int(count or 0) > 0
                    else ToolSemanticStatus.PARTIAL
                ),
                0.9 if valid and int(count or 0) > 0 else 0.45 if valid else 0.1,
                reason=None if valid else "memory retrieval result is incomplete",
            )
        if tool_name in CAREER_ADVISOR_TOOL_MANIFESTS:
            sample_count = result.get("sample_count")
            citation_count = result.get("citation_count")
            if sample_count is not None:
                try:
                    sample_count = max(0, int(sample_count))
                except (TypeError, ValueError):
                    return ResultVerification(
                        False,
                        ToolSemanticStatus.INVALID,
                        0.1,
                        reason="career advisor sample_count is not numeric",
                    )
            if citation_count is not None:
                try:
                    citation_count = max(0, int(citation_count))
                except (TypeError, ValueError):
                    return ResultVerification(
                        False,
                        ToolSemanticStatus.INVALID,
                        0.1,
                        reason="career advisor citation_count is not numeric",
                    )
            if tool_name == "compare_role_profiles":
                reports = result.get("reports")
                valid = isinstance(reports, list) and len(reports) >= 2
                return ResultVerification(
                    valid,
                    ToolSemanticStatus.VALID if valid else ToolSemanticStatus.INVALID,
                    0.9 if valid else 0.1,
                    reason=None if valid else "role comparison returned fewer than two reports",
                )
            if tool_name == "build_learning_roadmap":
                roadmap = result.get("roadmap")
                valid = isinstance(roadmap, list) and bool(roadmap)
                return ResultVerification(
                    valid,
                    ToolSemanticStatus.VALID if valid else ToolSemanticStatus.PARTIAL,
                    0.9 if valid else 0.3,
                    reason=None if valid else "learning roadmap is empty",
                )
            if tool_name == "analyze_resume_gap":
                valid = bool(result.get("resume_id")) and (
                    sample_count is not None or "missing_skills" in result
                )
                return ResultVerification(
                    valid,
                    ToolSemanticStatus.VALID if valid else ToolSemanticStatus.INVALID,
                    0.9 if valid else 0.1,
                    reason=None if valid else "resume gap result is incomplete",
                )
            if tool_name == "deep_dive_skill_requirements":
                skills = result.get("skills")
                valid = isinstance(skills, list) and bool(skills)
                return ResultVerification(
                    valid,
                    ToolSemanticStatus.VALID if valid else ToolSemanticStatus.PARTIAL,
                    0.85 if valid else 0.3,
                    reason=None if valid else "skill deep dive returned no details",
                )
            if sample_count == 0:
                return ResultVerification(
                    True,
                    ToolSemanticStatus.PARTIAL,
                    0.25,
                    reason="knowledge base returned no matching samples",
                )
            if sample_count is not None or citation_count is not None:
                return ResultVerification(
                    True,
                    ToolSemanticStatus.VALID,
                    0.85,
                    {"has_grounded_summary": True},
                    confidence=0.85,
                )
            return ResultVerification(
                True,
                ToolSemanticStatus.PARTIAL,
                0.5,
                reason="tool returned no compact evidence counters",
            )
        return ResultVerification(True, ToolSemanticStatus.UNKNOWN, 0.5, confidence=0.5)


class GoalValidator:
    def verify(
        self, goal: str, memory: dict[str, Any], *, waiting_for_user: bool = False
    ) -> GoalVerification:
        if waiting_for_user:
            return GoalVerification(False, ("user approval",), 0.95)
        results = memory.get("working", {}).get("tool_results", {})
        missing = []
        search_result = results.get("search_jobs")
        if "search_jobs" not in results:
            missing.append("job search")
        elif int(search_result.get("count", 0) or 0) <= 0:
            missing.append("matching jobs")
        if "retrieve_resume" not in results:
            missing.append("resume retrieval")
        rank_result = results.get("rank_jobs")
        score_result = results.get("score_job")
        if "rank_jobs" in results and int(rank_result.get("count", 0) or 0) <= 0:
            missing.append("ranked matching jobs")
        elif "rank_jobs" not in results and (
            "score_job" not in results or not score_result.get("job_id")
        ):
            missing.append("job ranking")
        return GoalVerification(not missing, tuple(missing), 0.9 if not missing else 0.4)


class ToolRecoveryManager:
    def decide(
        self,
        error: BaseException | None = None,
        *,
        attempt: int,
        max_retries: int,
        result_verification: ResultVerification | None = None,
    ) -> RecoveryAction:
        if result_verification is not None and not result_verification.valid:
            return RecoveryAction.REPLAN
        if isinstance(error, TimeoutError):
            return RecoveryAction.RETRY if attempt <= max_retries else RecoveryAction.ABORT
        if error is not None:
            message = str(error).casefold()
            if "permission" in message or "confirmation" in message or "not exposed" in message:
                return RecoveryAction.ASK_USER
            if "schema" in message or "argument" in message or "salary" in message:
                return RecoveryAction.REPAIR_ARGUMENTS
            if attempt <= max_retries:
                return RecoveryAction.RETRY
            return RecoveryAction.ABORT
        return RecoveryAction.REPLAN


class ToolCritic:
    """Small independent critic for ambiguous or risky decisions.

    This is intentionally deterministic. An LLM-based critic can be plugged in
    later for semantic relevance, but it must not replace these guardrails.
    """

    def review(
        self,
        manifest: ToolManifest,
        *,
        match_confidence: float,
        phase: str,
        confirmation_granted: bool,
    ) -> dict[str, Any]:
        if phase not in manifest.allowed_states:
            return {"approved": False, "issue": "tool is not allowed in this phase"}
        if (
            manifest.risk_level in {ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL}
            and not confirmation_granted
        ):
            return {"approved": False, "issue": "risky tool requires confirmation"}
        if match_confidence < 0.6:
            return {
                "approved": False,
                "issue": "tool capability match is below confidence threshold",
            }
        return {"approved": True, "issue": None}
