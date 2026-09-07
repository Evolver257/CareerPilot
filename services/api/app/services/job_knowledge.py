from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.llm.tokenization import (
    APPROXIMATE_TOKEN_COUNTER,
    TokenCounter,
    approximate_multilingual_tokens,
    max_prefix_end,
)
from app.models.entities import Job

JOB_KNOWLEDGE_VERSION = "JOB_KNOWLEDGE_V4"
JOB_KNOWLEDGE_CHUNKING_VERSION = "JD_SEMANTIC_V5_PROVIDER_TOKENS"
JOB_KNOWLEDGE_PARSER_VERSION = "JOB_EXTRACTION_V5"
JOB_KNOWLEDGE_CHUNK_CHAR_LIMIT = 1400
JOB_KNOWLEDGE_CHUNK_TOKEN_LIMIT = 110
_SECTION_HEADINGS = {
    "岗位职责",
    "工作职责",
    "职位职责",
    "职责描述",
    "任职要求",
    "任职条件",
    "职位要求",
    "岗位要求",
    "工作要求",
    "资格要求",
    "岗位描述",
    "职位描述",
    "工作内容",
    "加分项",
}
_NORMALIZED_SECTION_HEADINGS = {
    re.sub(r"[^\w+#]+", "", unicodedata.normalize("NFKC", item).casefold())
    for item in _SECTION_HEADINGS
}
_REQUIREMENT_CUES = re.compile(
    r"精通|熟练|熟悉|掌握|了解|优先|加分|必须|要求|具备|能够|至少|经验|负责|参与|开发",
    re.I,
)


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
    "function calling": "Function Calling",
    "function call": "Function Calling",
    "tool calling": "Function Calling",
    "tool call": "Function Calling",
    "工具调用": "Function Calling",
    "函数调用": "Function Calling",
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
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "java": "Java",
    "fastapi": "FastAPI",
    "rest api": "REST API",
    "restful api": "REST API",
    "api service": "REST API",
    "api 服务": "REST API",
    "接口服务": "REST API",
    "接口开发": "REST API",
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


def normalize_experience_requirement(value: str | None) -> str:
    """Map free-form JD experience text to a small, trustworthy taxonomy.

    Extractors occasionally place an entire qualification sentence in the
    experience field. Unknown prose must therefore stay empty instead of
    becoming a new distribution label.
    """

    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    if not text:
        return ""

    year_values = [
        int(item)
        for item in re.findall(r"(?<!\d)(\d{1,2})\s*(?:\+|年以上|年|年经验)", text)
        if 0 < int(item) <= 20
    ]
    range_values = [
        (int(low), int(high))
        for low, high in re.findall(
            r"(?<!\d)(\d{1,2})\s*(?:-|–|—|~|～|至|到)\s*(\d{1,2})\s*年",
            text,
        )
        if 0 < int(low) <= int(high) <= 20
    ]
    if range_values:
        low = min(item[0] for item in range_values)
        high = max(item[1] for item in range_values)
    elif year_values:
        low = min(year_values)
        high = max(year_values)
    else:
        low = high = 0

    if low or high:
        if high <= 1:
            return "1年以内"
        if low >= 5:
            return "5年以上"
        if low >= 3:
            return "3-5年"
        return "1-3年"

    unrestricted_patterns = (
        r"经验\s*(?:不\s*限|无要求)",
        r"(?:不\s*限|无要求)\s*经验",
        r"(?:无需|不要求)\s*(?:相关)?经验",
        r"(?:接受|欢迎)?\s*应届(?:生|毕业生)?",
        r"在校(?:生|学生)",
    )
    if any(re.search(pattern, text) for pattern in unrestricted_patterns):
        return "应届/经验不限"
    return ""


def build_job_knowledge_chunks(
    job: Job,
    token_counter: TokenCounter | None = None,
) -> list[JobKnowledgeChunkDraft]:
    """Create semantic JD sections without asking an LLM to rewrite source text."""

    counter = token_counter or APPROXIMATE_TOKEN_COUNTER

    structured = (job.normalized_data or {}).get("structured_job") or {}
    requirements = (job.normalized_data or {}).get("requirements") or {}
    company = str((job.raw_data or {}).get("company_name") or "").strip()
    if not company and job.company is not None:
        company = job.company.name

    responsibilities = _list_values(
        structured.get("responsibilities"), requirements.get("responsibilities"),
        (job.normalized_data or {}).get("pipeline", {}).get("responsibilities"),
    )
    qualifications = _list_values(
        requirements.get("qualifications"), requirements.get("preferred_qualifications"),
        (job.normalized_data or {}).get("pipeline", {}).get("requirements"),
    )
    pipeline = (job.normalized_data or {}).get("pipeline") or {}
    required_skills = _list_values(
        structured.get("required_skills"),
        [skill.skill_name for skill in job.skills if skill.skill_type == "required"],
    )
    preferred_skills = _list_values(
        structured.get("preferred_skills"),
        [skill.skill_name for skill in job.skills if skill.skill_type in {"preferred", "optional"}],
    )
    persisted_requirements = job.__dict__.get("requirements", [])
    direction_values = _unique_values([
        str((item.requirement_metadata or {}).get("label") or item.normalized_value)
        for item in persisted_requirements
        if item.requirement_type == "direction"
    ])
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
        ("direction", "职能方向", direction_values),
        (
            "responsibilities",
            "岗位职责",
            responsibilities,
        ),
        (
            "requirements",
            "任职条件",
            qualifications,
        ),
        (
            "required_skills",
            "必备技能",
            _skills_with_evidence(required_skills, job.description, preferred=False),
        ),
        (
            "preferred_skills",
            "加分技能",
            _skills_with_evidence(preferred_skills, job.description, preferred=True),
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
                    *_list_values(
                        structured.get("benefits"), requirements.get("benefits"),
                        pipeline.get("benefits"),
                    ),
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
        chunker = _atomic_section_chunks if section_type in {
            "direction", "required_skills", "preferred_skills", "education", "experience"
        } else _section_chunks
        for index, content in enumerate(chunker(heading, values, counter)):
            drafts.append(_draft(section_type, content, job, index, counter))

    covered_values = _unique_values(
        [
            *responsibilities,
            *qualifications,
            *required_skills,
            *preferred_skills,
            *_list_values(structured.get("summary")),
        ]
    )
    residual_lines = _uncovered_source_lines(job.description, covered_values)
    for index, content in enumerate(_section_chunks("原文补充", residual_lines, counter)):
        drafts.append(_draft("source_context", content, job, index, counter))
    return drafts


def _draft(
    section_type: str,
    content: str,
    job: Job,
    index: int,
    token_counter: TokenCounter,
) -> JobKnowledgeChunkDraft:
    company = str((job.raw_data or {}).get("company_name") or "").strip()
    if not company and job.company is not None:
        company = job.company.name
    return JobKnowledgeChunkDraft(
        section_type=section_type,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        token_count=token_counter.count(content),
        metadata={
            "section_type": section_type,
            "chunk_index": index,
            "job_title": job.title,
            "company": company,
            "location": job.location,
            "platform": job.platform,
            "education": job.education_requirement,
            "experience": job.experience_requirement,
            "source_url": job.source_url,
            "evidence_type": "source_text",
            "quality_score": job.data_quality_score,
            "quality_level": job.data_quality_level,
            "lifecycle_status": job.lifecycle_status,
            "evidence": ((job.normalized_data or {}).get("pipeline") or {}).get("evidence", []),
            "tokenizer_signature": token_counter.signature,
            "token_count_exact": token_counter.exact,
            "chunking_version": JOB_KNOWLEDGE_CHUNKING_VERSION,
        },
    )


def _section_chunks(
    heading: str,
    values: list[str],
    token_counter: TokenCounter,
) -> list[str]:
    clean_values = _unique_values(values)
    if not clean_values:
        return []
    chunks: list[str] = []
    current = f"## {heading}"
    expanded_values = _unique_values(
        [
            segment
            for value in clean_values
            for segment in _split_value(value, heading, token_counter)
        ]
    )
    for value in expanded_values:
        line = f"- {value}"
        if len(current) > len(f"## {heading}") and (
            len(current) + len(line) + 1 > JOB_KNOWLEDGE_CHUNK_CHAR_LIMIT
            or token_counter.count(f"{current}\n{line}") > JOB_KNOWLEDGE_CHUNK_TOKEN_LIMIT
        ):
            chunks.append(current)
            current = f"## {heading}\n{line}"
        else:
            current = f"{current}\n{line}"
    if current != f"## {heading}":
        chunks.append(current)
    return chunks


def _atomic_section_chunks(
    heading: str,
    values: list[str],
    token_counter: TokenCounter,
) -> list[str]:
    """Keep every scoring requirement independently retrievable and citeable."""
    return [
        f"## {heading}\n- {segment}"
        for value in _unique_values(values)
        for segment in _split_value(value, heading, token_counter)
    ]


def estimate_knowledge_tokens(value: str) -> int:
    """Compatibility fallback; production Qwen indexing uses its tokenizer."""

    return approximate_multilingual_tokens(value)


def _split_value(value: str, heading: str, token_counter: TokenCounter) -> list[str]:
    char_budget = JOB_KNOWLEDGE_CHUNK_CHAR_LIMIT - len(f"## {heading}\n- ")
    token_budget = JOB_KNOWLEDGE_CHUNK_TOKEN_LIMIT - token_counter.count(
        f"## {heading}\n- "
    )
    if len(value) <= char_budget and token_counter.count(value) <= token_budget:
        return [value]
    units = [
        item.strip()
        for item in re.split(r"(?<=[。！？!?；;])\s*|(?<=[，,：:])\s*", value)
        if item.strip()
    ]
    segments: list[str] = []
    current = ""
    for unit in units or [value]:
        pieces = _hard_windows(unit, char_budget, token_budget, token_counter)
        for piece in pieces:
            candidate = f"{current}{piece}" if current else piece
            if current and (
                len(candidate) > char_budget or token_counter.count(candidate) > token_budget
            ):
                segments.append(current)
                current = piece
            else:
                current = candidate
    if current:
        segments.append(current)
    return segments


def _hard_windows(
    value: str,
    char_limit: int,
    token_limit: int,
    token_counter: TokenCounter,
) -> list[str]:
    if len(value) <= char_limit and token_counter.count(value) <= token_limit:
        return [value]
    result: list[str] = []
    start = 0
    while start < len(value):
        end = start + max_prefix_end(
            value[start:],
            max_chars=char_limit,
            max_tokens=token_limit,
            counter=token_counter,
        )
        result.append(value[start:end].strip())
        start = end
    return [item for item in result if item]


def _skills_with_evidence(skills: list[str], source: str, *, preferred: bool) -> list[str]:
    source_lines = _source_evidence_units(source)
    result: list[str] = []
    for skill in _unique_values(skills):
        matches = [line for line in source_lines if _contains_skill(line, skill)]
        matches.sort(key=lambda line: (not bool(_REQUIREMENT_CUES.search(line)), len(line)))
        evidence = matches[:2]
        label = "加分技能" if preferred else "技能"
        item = f"{label}：{canonicalize_skill(skill)}"
        if evidence:
            item += f"；原文要求：{'；'.join(evidence)}"
        result.append(item)
    return _unique_values(result)


def _source_evidence_units(source: str) -> list[str]:
    units: list[str] = []
    for line in _split_source(source):
        units.extend(
            item.strip() for item in re.split(r"(?<=[。！？!?；;])\s*", line) if item.strip()
        )
    return _unique_values(units)


def _contains_skill(line: str, skill: str) -> bool:
    canonical = canonicalize_skill(skill)
    terms = {skill, canonical}
    terms.update(alias for alias, target in SKILL_ALIASES.items() if target == canonical)
    normalized_line = unicodedata.normalize("NFKC", line).casefold()
    for term in terms:
        clean = unicodedata.normalize("NFKC", term).strip().casefold()
        if not clean:
            continue
        if re.fullmatch(r"[a-z0-9_+#.\-/ ]+", clean):
            pattern = rf"(?<![a-z0-9_]){re.escape(clean)}(?![a-z0-9_])"
            if re.search(pattern, normalized_line):
                return True
        elif clean in normalized_line:
            return True
    return False


def _uncovered_source_lines(source: str, covered_values: list[str]) -> list[str]:
    covered = [_normalize_evidence(value) for value in covered_values]
    result: list[str] = []
    for line in _split_source(source):
        normalized = _normalize_evidence(line)
        if not normalized or normalized in _NORMALIZED_SECTION_HEADINGS:
            continue
        represented = any(
            len(item) >= 6
            and (normalized == item or (len(item) >= len(normalized) * 0.75 and normalized in item))
            for item in covered
        )
        if not represented:
            result.append(line)
    return _unique_values(result)


def _normalize_evidence(value: str) -> str:
    return re.sub(r"[^\w+#]+", "", unicodedata.normalize("NFKC", value).casefold())


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
