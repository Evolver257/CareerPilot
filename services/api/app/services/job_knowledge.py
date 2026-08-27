from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.llm.usage import estimate_tokens
from app.models.entities import Job

JOB_KNOWLEDGE_VERSION = "JOB_KNOWLEDGE_V1"
JOB_KNOWLEDGE_PARSER_VERSION = "JOB_EXTRACTION_V3"
JOB_KNOWLEDGE_CHUNK_CHAR_LIMIT = 1400


@dataclass(frozen=True)
class JobKnowledgeChunkDraft:
    section_type: str
    content: str
    content_hash: str
    token_count: int
    metadata: dict[str, Any]


SKILL_ALIASES: dict[str, str] = {
    "大语言模型": "LLM",
    "large language model": "LLM",
    "llm": "LLM",
    "rag": "RAG",
    "检索增强生成": "RAG",
    "检索增强": "RAG",
    "ai agent": "AI Agent",
    "agent": "AI Agent",
    "智能体": "AI Agent",
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "pytorch": "PyTorch",
    "torch": "PyTorch",
    "tensorflow": "TensorFlow",
    "ros": "ROS",
    "ros2": "ROS2",
    "c++": "C++",
    "cpp": "C++",
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java": "Java",
    "fastapi": "FastAPI",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "sql": "SQL",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "redis": "Redis",
    "git": "Git",
}

SKILL_CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ai", ("LLM", "RAG", "AI Agent", "LangChain", "LangGraph", "PyTorch", "TensorFlow")),
    ("robotics", ("ROS", "ROS2", "C++")),
    ("backend", ("Python", "FastAPI", "Java", "SQL", "MySQL", "PostgreSQL", "Redis")),
    ("frontend", ("JavaScript", "TypeScript")),
    ("devops", ("Docker", "Kubernetes", "Git")),
)


def normalize_skill_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").strip().casefold()
    normalized = re.sub(r"[\s_\-]+", " ", normalized)
    return normalized.strip(" .,，、:：;；()（）[]【】")


def canonicalize_skill(value: str) -> str:
    clean = (value or "").strip()
    if not clean:
        return ""
    return SKILL_ALIASES.get(normalize_skill_name(clean), clean)


def skill_category(canonical_name: str) -> str:
    for category, names in SKILL_CATEGORIES:
        if canonical_name in names:
            return category
    return "other"


def build_job_knowledge_chunks(job: Job) -> list[JobKnowledgeChunkDraft]:
    """Create semantic JD sections without asking an LLM to rewrite source text."""

    structured = (job.normalized_data or {}).get("structured_job") or {}
    requirements = (job.normalized_data or {}).get("requirements") or {}
    company = str((job.raw_data or {}).get("company_name") or "").strip()
    if not company and job.company is not None:
        company = job.company.name

    fields: list[tuple[str, str, list[str]]] = [
        (
            "overview",
            "岗位概览",
            _unique_values(
                [
                    _label_value("岗位", job.title),
                    _label_value("岗位族群", structured.get("role_category")),
                    _label_value("级别", structured.get("level")),
                    _label_value("公司", company),
                    _label_value("地点", job.location or structured.get("location")),
                    _label_value("工作类型", job.job_type or structured.get("job_type")),
                    _label_value("简介", structured.get("summary")),
                ]
            ),
        ),
        (
            "responsibilities",
            "岗位职责",
            _list_values(structured.get("responsibilities"), requirements.get("responsibilities")),
        ),
        (
            "requirements",
            "任职条件",
            _list_values(
                requirements.get("qualifications"),
                requirements.get("preferred_qualifications"),
            ),
        ),
        (
            "required_skills",
            "必备技能",
            _list_values(
                structured.get("required_skills"),
                [skill.skill_name for skill in job.skills if skill.skill_type == "required"],
            ),
        ),
        (
            "preferred_skills",
            "加分技能",
            _list_values(
                structured.get("preferred_skills"),
                [
                    skill.skill_name
                    for skill in job.skills
                    if skill.skill_type in {"preferred", "optional"}
                ],
            ),
        ),
        (
            "education",
            "学历要求",
            _list_values(structured.get("education_requirement"), job.education_requirement),
        ),
        (
            "experience",
            "经验要求",
            _list_values(structured.get("experience_requirement"), job.experience_requirement),
        ),
        (
            "salary_benefits",
            "薪资福利",
            _unique_values(
                [
                    _salary_line(job),
                    *_list_values(structured.get("benefits"), requirements.get("benefits")),
                ]
            ),
        ),
        (
            "business_domain",
            "业务关键词",
            _list_values(structured.get("keywords")),
        ),
    ]

    drafts: list[JobKnowledgeChunkDraft] = []
    for section_type, heading, values in fields:
        for index, content in enumerate(_section_chunks(heading, values)):
            drafts.append(_draft(section_type, content, job, index))

    has_requirement_content = any(
        draft.section_type
        in {"responsibilities", "requirements", "required_skills", "preferred_skills"}
        for draft in drafts
    )
    if not has_requirement_content:
        for index, content in enumerate(
            _section_chunks("原始岗位描述", _split_source(job.description))
        ):
            drafts.append(_draft("other", content, job, index))
    return drafts


def _draft(section_type: str, content: str, job: Job, index: int) -> JobKnowledgeChunkDraft:
    company = str((job.raw_data or {}).get("company_name") or "").strip()
    if not company and job.company is not None:
        company = job.company.name
    return JobKnowledgeChunkDraft(
        section_type=section_type,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        token_count=estimate_tokens(content),
        metadata={
            "section_type": section_type,
            "chunk_index": index,
            "job_title": job.title,
            "company": company,
            "location": job.location,
            "platform": job.platform,
            "education": job.education_requirement,
            "experience": job.experience_requirement,
        },
    )


def _section_chunks(heading: str, values: list[str]) -> list[str]:
    clean_values = _unique_values(values)
    if not clean_values:
        return []
    chunks: list[str] = []
    current = f"## {heading}"
    for value in clean_values:
        line = f"- {value}"
        if (
            len(current) > len(f"## {heading}")
            and len(current) + len(line) + 1 > JOB_KNOWLEDGE_CHUNK_CHAR_LIMIT
        ):
            chunks.append(current)
            current = f"## {heading}\n{line}"
        else:
            current = f"{current}\n{line}"
    if current != f"## {heading}":
        chunks.append(current)
    return chunks


def _split_source(value: str) -> list[str]:
    return [line.strip() for line in re.split(r"\n+", value or "") if line.strip()]


def _label_value(label: str, value: Any) -> str:
    clean = str(value or "").strip()
    return f"{label}：{clean}" if clean else ""


def _list_values(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str):
            result.extend(_split_source(value))
        elif isinstance(value, list | tuple | set):
            result.extend(str(item).strip() for item in value if str(item).strip())
    return _unique_values(result)


def _unique_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _salary_line(job: Job) -> str:
    raw = job.raw_data or {}
    salary = next(
        (str(raw[key]).strip() for key in ("salary_text", "salary", "salaryText") if raw.get(key)),
        "",
    )
    if salary:
        return f"薪资：{salary}"
    if job.salary_min is None and job.salary_max is None:
        return ""
    low = job.salary_min if job.salary_min is not None else job.salary_max
    high = job.salary_max if job.salary_max is not None else job.salary_min
    suffix = "元/天" if (job.job_type or "").lower() in {"internship", "实习"} else "K/月"
    return f"薪资：{low}-{high}{suffix}"
