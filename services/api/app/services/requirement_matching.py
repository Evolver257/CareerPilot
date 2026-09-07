from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha1
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job, JobRequirement, JobSkill, Resume
from app.schemas.resumes import ResumeProfile
from app.services.job_knowledge import SKILL_ALIASES, canonicalize_skill

JOB_REQUIREMENT_VERSION = "JD_REQUIREMENT_V3_3"

_CRITICAL_CUE = re.compile(
    r"核心要求|关键要求|硬性|不可缺少|必须(?:具备|精通)|不可替代", re.I
)
_MUST_CUE = re.compile(r"必须|要求|精通|熟练掌握|必备|must(?:[- ]have)?|required", re.I)
_PREFERRED_CUE = re.compile(r"优先|加分|更佳|最好|有则更好|nice\s+to\s+have|preferred", re.I)
_CONTEXT_CUE = re.compile(r"了解|参与|接触|有机会参与|团队(?:目前)?使用|技术栈包括|负责", re.I)
_UNRESTRICTED = re.compile(r"不限|无要求|无需|应届|在校生|fresh\s*graduate", re.I)
_OPTIONAL_EXPERIENCE = re.compile(r"经验.{0,8}(?:优先|加分|更佳)|有.{0,12}经验者?优先", re.I)
_GENERIC_SKILLS = {"ai", "artificial intelligence", "ai agent", "agent", "prompt", "人工智能"}

_DIRECTION_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sales", ("销售", "商务", "bd", "客户经理", "account executive", "business development")),
    ("content", ("编剧", "文案", "编辑", "内容创作", "短剧", "writer", "content creator")),
    ("operations", ("运营", "用户增长", "增长", "训练师", "community", "operation")),
    (
        "product",
        ("产品经理", "产品实习", "产品助理", "产品工程师", "product manager", "产品策划"),
    ),
    ("teaching", ("讲师", "教师", "授课", "课程老师", "trainer", "instructor")),
    ("design", ("设计师", "视觉设计", "交互设计", "ui/ux", "ux", "designer")),
    (
        "algorithm",
        (
            "算法",
            "模型训练",
            "机器学习",
            "深度学习",
            "computer vision",
            "nlp",
            "research scientist",
        ),
    ),
    ("data", ("数据分析", "数据科学", "data analyst", "data scientist", "商业分析")),
    (
        "engineering",
        ("工程师", "开发", "研发", "后端", "前端", "全栈", "软件", "developer", "engineer"),
    ),
)

_ADJACENT_DIRECTIONS = {
    ("engineering", "algorithm"),
    ("algorithm", "engineering"),
    ("product", "operations"),
    ("operations", "product"),
    ("data", "algorithm"),
    ("algorithm", "data"),
}


@dataclass(frozen=True)
class RequirementDraft:
    requirement_type: str
    value: str
    source_text: str
    source_section: str
    importance: float
    is_hard: bool
    is_critical: bool
    confidence: float
    specificity: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RequirementEvaluation:
    requirement: JobRequirement
    status: str
    score: float
    evidence: list[dict[str, Any]]
    match_method: str
    confidence: float
    deduction: float = 0.0
    hard_constraint: bool = False


def infer_direction(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    for direction, terms in _DIRECTION_PATTERNS:
        if any(_term_present(normalized, term.casefold()) for term in terms):
            return direction
    return "unknown"


def extract_job_requirements(
    job: Job, skills: Iterable[JobSkill] | None = None
) -> list[RequirementDraft]:
    skill_rows = list(skills if skills is not None else job.skills)
    source_units = _source_units(job.description)
    direction = infer_direction(job.title)
    if direction == "unknown":
        structured = (job.normalized_data or {}).get("structured_job") or {}
        direction = infer_direction(str(structured.get("role_category") or ""))

    drafts = [
        RequirementDraft(
            requirement_type="direction",
            value=direction,
            source_text=job.title,
            source_section="title",
            importance=1.0,
            is_hard=direction != "unknown",
            is_critical=False,
            confidence=0.95 if direction != "unknown" else 0.25,
            specificity=1.0 if direction != "unknown" else 0.2,
            metadata={"label": _direction_label(direction)},
        )
    ]

    seen: set[tuple[str, str]] = set()
    for skill in skill_rows:
        default_type = (
            "preferred_skill"
            if skill.skill_type in {"preferred", "optional"}
            else "must_have_skill"
        )
        evidence = _find_evidence(source_units, skill.skill_name)
        requirement_type = _classify_skill_requirement(default_type, evidence)
        canonical = canonicalize_skill(skill.skill_name)
        key = (requirement_type, canonical.casefold())
        if not canonical or key in seen:
            continue
        seen.add(key)
        critical = requirement_type == "must_have_skill" and bool(_CRITICAL_CUE.search(evidence))
        specificity = 0.35 if canonical.casefold() in _GENERIC_SKILLS else 0.9
        group_metadata = _skill_group_metadata(evidence, canonical, skill_rows)
        drafts.append(
            RequirementDraft(
                requirement_type=requirement_type,
                value=canonical,
                source_text=evidence or skill.skill_name,
                source_section="requirements",
                importance=max(0.0, min(1.0, skill.importance)),
                is_hard=requirement_type == "must_have_skill",
                is_critical=critical,
                confidence=max(0.0, min(1.0, skill.confidence)),
                specificity=specificity,
                metadata={"original_value": skill.skill_name, **group_metadata},
            )
        )

    structured = (job.normalized_data or {}).get("structured_job") or {}
    supplemental: list[tuple[str, str]] = []
    for key, kind in (
        ("required_skills", "must_have_skill"),
        ("preferred_skills", "preferred_skill"),
    ):
        values = structured.get(key, [])
        if isinstance(values, list):
            supplemental.extend((str(value).strip(), kind) for value in values)
    for unit in source_units:
        if not _MUST_CUE.search(unit):
            continue
        supplemental.extend(
            (match, "must_have_skill")
            for match in re.findall(
                r"(?:必须(?:精通|掌握|熟悉)?|精通|熟练掌握|required|must(?:[- ]have)?)\s*"
                r"([A-Za-z][A-Za-z0-9+.#-]{1,40})",
                unit,
                re.I,
            )
        )
    for value, requirement_type in supplemental:
        canonical = canonicalize_skill(value)
        evidence = _find_evidence(source_units, value)
        requirement_type = _classify_skill_requirement(requirement_type, evidence)
        key = (requirement_type, canonical.casefold())
        if not canonical or key in seen:
            continue
        seen.add(key)
        critical = requirement_type == "must_have_skill" and bool(_CRITICAL_CUE.search(evidence))
        group_metadata = _skill_group_metadata(evidence, canonical, skill_rows)
        drafts.append(
            RequirementDraft(
                requirement_type=requirement_type,
                value=canonical,
                source_text=evidence or value,
                source_section="requirements",
                importance=0.85 if critical else 0.65,
                is_hard=requirement_type == "must_have_skill",
                is_critical=critical,
                confidence=0.78,
                specificity=0.9,
                metadata={"extraction": "structured_or_critical_phrase", **group_metadata},
            )
        )

    education = (job.education_requirement or "").strip()
    if education:
        education_metadata = _parse_education_requirement(education)
        drafts.append(
            RequirementDraft(
                requirement_type="education",
                value=education,
                source_text=_find_evidence(source_units, education) or education,
                source_section="requirements",
                importance=0.9,
                is_hard=not bool(_UNRESTRICTED.search(education)),
                is_critical=False,
                confidence=0.9,
                specificity=0.9,
                metadata=education_metadata,
            )
        )
    experience = (job.experience_requirement or "").strip()
    if experience:
        experience_optional = bool(_OPTIONAL_EXPERIENCE.search(experience))
        drafts.append(
            RequirementDraft(
                requirement_type="experience",
                value=experience,
                source_text=_find_evidence(source_units, experience) or experience,
                source_section="requirements",
                importance=0.9,
                is_hard=not bool(_UNRESTRICTED.search(experience)) and not experience_optional,
                is_critical=False,
                confidence=0.85,
                specificity=0.85,
                metadata={
                    "required_years": _required_years(experience),
                    "optional": experience_optional,
                },
            )
        )
    return drafts


async def sync_job_requirements(session: AsyncSession, job: Job) -> list[JobRequirement]:
    """Replace only derived requirement rows; source jobs and RAG documents remain untouched."""
    await session.flush()
    skills = list((await session.scalars(select(JobSkill).where(JobSkill.job_id == job.id))).all())
    drafts = extract_job_requirements(job, skills)
    await session.execute(delete(JobRequirement).where(JobRequirement.job_id == job.id))
    rows = [
        JobRequirement(
            job_id=job.id,
            requirement_type=item.requirement_type,
            normalized_value=item.value[:300],
            source_text=item.source_text,
            source_section=item.source_section,
            importance=item.importance,
            is_hard=item.is_hard,
            is_critical=item.is_critical,
            extraction_confidence=item.confidence,
            specificity=item.specificity,
            parser_version=JOB_REQUIREMENT_VERSION,
            requirement_metadata=item.metadata,
        )
        for item in drafts
    ]
    session.add_all(rows)
    await session.flush()
    return rows


def evaluate_requirements(
    requirements: Iterable[JobRequirement], resume: Resume, profile: ResumeProfile
) -> list[RequirementEvaluation]:
    evaluations = [_evaluate(item, resume, profile) for item in requirements]
    return _resolve_skill_groups(evaluations)


def _evaluate(
    item: JobRequirement, resume: Resume, profile: ResumeProfile
) -> RequirementEvaluation:
    if item.requirement_type == "direction":
        return _evaluate_direction(item, resume, profile)
    if item.requirement_type in {"must_have_skill", "preferred_skill"}:
        return _evaluate_skill(item, resume, profile)
    if item.requirement_type == "education":
        return _evaluate_education(item, profile)
    if item.requirement_type == "experience":
        return _evaluate_experience(item, resume, profile)
    return RequirementEvaluation(item, "unknown", 50.0, [], "unknown", 0.2)


def _evaluate_direction(
    item: JobRequirement, resume: Resume, profile: ResumeProfile
) -> RequirementEvaluation:
    directions: list[str] = []
    for value in [*profile.target_roles, *[entry.role for entry in profile.experience]]:
        direction = infer_direction(value)
        if direction != "unknown" and direction not in directions:
            directions.append(direction)
    inferred = infer_direction(" ".join((profile.summary, resume.raw_text or "")))
    if inferred != "unknown" and inferred not in directions:
        directions.append(inferred)
    target = item.normalized_value
    if target == "unknown" or not directions:
        return RequirementEvaluation(item, "unknown", 50.0, [], "taxonomy", 0.35)
    if target in directions:
        score, status = 100.0, "matched"
    elif any((candidate, target) in _ADJACENT_DIRECTIONS for candidate in directions):
        score, status = 72.0, "partial"
    else:
        score, status = 15.0, "missing"
    evidence = [{"source": "resume_direction", "text": _direction_label(directions[0])}]
    return RequirementEvaluation(
        item, status, score, evidence, "role_taxonomy", 0.9, hard_constraint=status == "missing"
    )


def _evaluate_skill(
    item: JobRequirement, resume: Resume, profile: ResumeProfile
) -> RequirementEvaluation:
    if item.requirement_type == "context_skill":
        required = False
    else:
        required = item.requirement_type == "must_have_skill"
    target = _skill_key(item.normalized_value)
    profile_skills = {_skill_key(skill): skill for skill in profile.skills}
    if target in profile_skills:
        return RequirementEvaluation(
            item,
            "matched",
            90.0,
            [{"source": "skills", "text": profile_skills[target]}],
            "exact_skill",
            0.95,
        )
    units = _resume_units(resume, profile)
    evidence = next((unit for unit in units if _skill_present(unit, item.normalized_value)), "")
    if evidence:
        return RequirementEvaluation(
            item,
            "matched",
            100.0,
            [{"source": "resume_evidence", "text": evidence[:500]}],
            "exact_evidence",
            0.9,
        )
    deduction = 0.0
    if required and not item.is_critical:
        deduction = round(max(10.0, min(20.0, 10.0 + 10.0 * item.importance * item.specificity)), 2)
    return RequirementEvaluation(
        item,
        "missing",
        0.0,
        [],
        "no_evidence",
        max(0.65, item.extraction_confidence),
        deduction=deduction,
        hard_constraint=item.is_critical,
    )


def _evaluate_education(item: JobRequirement, profile: ResumeProfile) -> RequirementEvaluation:
    if _UNRESTRICTED.search(item.normalized_value):
        return RequirementEvaluation(item, "not_required", 100.0, [], "explicit_unrestricted", 0.95)
    metadata = item.requirement_metadata or {}
    accepted = [int(level) for level in metadata.get("accepted_levels", []) if int(level) > 0]
    minimum = int(metadata.get("minimum_level") or 0)
    required = minimum or (min(accepted) if accepted else _education_level(item.normalized_value))
    candidate_text = " ".join(entry.degree for entry in profile.education)
    candidate = _education_level(candidate_text)
    if required == 0:
        return RequirementEvaluation(item, "unknown", 50.0, [], "unparsed", 0.35)
    if minimum:
        matches = candidate >= minimum
    elif accepted:
        matches = candidate in accepted
    else:
        matches = candidate >= required
    if matches:
        return RequirementEvaluation(
            item,
            "matched",
            100.0,
            [{"source": "education", "text": candidate_text}],
            "degree_level",
            0.95,
        )
    return RequirementEvaluation(
        item,
        "missing",
        0.0,
        [{"source": "education", "text": candidate_text}] if candidate_text else [],
        "degree_level",
        0.95,
        hard_constraint=True,
    )


def _evaluate_experience(
    item: JobRequirement, resume: Resume, profile: ResumeProfile
) -> RequirementEvaluation:
    if _UNRESTRICTED.search(item.normalized_value):
        return RequirementEvaluation(item, "not_required", 100.0, [], "explicit_unrestricted", 0.95)
    required = _required_years(item.normalized_value)
    if required <= 0:
        return RequirementEvaluation(item, "unknown", 50.0, [], "unparsed", 0.35)
    candidate = _candidate_years(resume, profile)
    if candidate >= required:
        return RequirementEvaluation(
            item,
            "matched",
            100.0,
            [{"source": "experience", "text": f"约 {candidate:g} 年"}],
            "year_gap",
            0.85,
        )
    gap = required - candidate
    score = max(0.0, round(candidate / required * 100, 2))
    over_threshold = gap > max(1.0, required * 0.35)
    return RequirementEvaluation(
        item,
        "missing" if over_threshold else "partial",
        score,
        [{"source": "experience", "text": f"约 {candidate:g} 年"}] if candidate else [],
        "year_gap",
        0.8,
        hard_constraint=over_threshold,
    )


def _source_units(text: str) -> list[str]:
    return [
        part.strip(" -•\t")
        for part in re.split(r"[\r\n]+|(?<=[。！？；;])", text or "")
        if part.strip(" -•\t")
    ]


def _find_evidence(units: list[str], term: str) -> str:
    clean = unicodedata.normalize("NFKC", term or "").casefold()
    words = [word for word in re.split(r"[,，/、\s]+", clean) if len(word) >= 2]
    return next(
        (unit for unit in units if clean in unicodedata.normalize("NFKC", unit).casefold()),
        next(
            (
                unit
                for unit in units
                if words
                and any(word in unicodedata.normalize("NFKC", unit).casefold() for word in words)
            ),
            "",
        ),
    )


def _resume_units(resume: Resume, profile: ResumeProfile) -> list[str]:
    values = [resume.raw_text or "", profile.summary]
    values.extend(
        project.description + " " + " ".join(project.technologies + project.highlights)
        for project in profile.projects
    )
    values.extend(entry.role + " " + " ".join(entry.bullets) for entry in profile.experience)
    return _source_units("\n".join(values))


def _skill_key(value: str) -> str:
    canonical = canonicalize_skill(value)
    return re.sub(r"[^a-z0-9+#]", "", canonical.casefold())


def _skill_present(text: str, skill: str) -> bool:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    canonical = canonicalize_skill(skill)
    terms = {canonical, skill}
    terms.update(alias for alias, target in SKILL_ALIASES.items() if target == canonical)
    for term in terms:
        clean = unicodedata.normalize("NFKC", term or "").casefold().strip()
        if not clean:
            continue
        if re.fullmatch(r"[a-z0-9+#. ]+", clean):
            pattern = re.escape(clean).replace(r"\ ", r"\s+")
            if re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", normalized):
                return True
        elif clean in normalized:
            return True
    return False


def _classify_skill_requirement(default_type: str, source_text: str) -> str:
    if _PREFERRED_CUE.search(source_text or ""):
        return "preferred_skill"
    if _CONTEXT_CUE.search(source_text or "") and not _MUST_CUE.search(source_text or ""):
        return "context_skill"
    return default_type


def _skill_group_metadata(
    source_text: str, canonical: str, skill_rows: Iterable[JobSkill]
) -> dict[str, Any]:
    text = unicodedata.normalize("NFKC", source_text or "").strip()
    independent = {
        "group_id": f"skill:{_skill_key(canonical)}",
        "group_operator": "ALL_OF",
        "minimum_match_count": 1,
    }
    if not text:
        return independent
    number_match = re.search(r"至少\s*([一二两三四五六七八九\d]+)\s*(?:种|项|个)", text)
    alternative_cue = bool(
        number_match
        or re.search(
            r"/|或|之一|任一|任意.{0,2}门|等(?:框架|技术|语言|工具|数据库|组件)",
            text,
        )
    )
    if not alternative_cue:
        return independent
    members = sorted(
        {
            canonicalize_skill(row.skill_name)
            for row in skill_rows
            if _skill_present(text, row.skill_name)
        },
        key=str.casefold,
    )
    if len(members) < 2:
        return independent
    minimum = _chinese_number(number_match.group(1)) if number_match else 1
    minimum = max(1, min(minimum, len(members)))
    operator = "AT_LEAST_N" if minimum > 1 else "ANY_OF"
    digest = sha1((text.casefold() + "|" + "|".join(members)).encode()).hexdigest()[:12]
    return {
        "group_id": f"skill-group:{digest}",
        "group_operator": operator,
        "minimum_match_count": minimum,
        "group_members": members,
    }


def _resolve_skill_groups(
    evaluations: list[RequirementEvaluation],
) -> list[RequirementEvaluation]:
    grouped: dict[str, list[int]] = {}
    for index, evaluation in enumerate(evaluations):
        if evaluation.requirement.requirement_type not in {"must_have_skill", "preferred_skill"}:
            continue
        metadata = evaluation.requirement.requirement_metadata or {}
        operator = str(metadata.get("group_operator") or "ALL_OF")
        group_id = str(metadata.get("group_id") or f"requirement:{evaluation.requirement.id}")
        if operator in {"ANY_OF", "AT_LEAST_N"}:
            grouped.setdefault(group_id, []).append(index)

    resolved = list(evaluations)
    for indexes in grouped.values():
        items = [resolved[index] for index in indexes]
        minimum = max(
            1,
            int((items[0].requirement.requirement_metadata or {}).get("minimum_match_count") or 1),
        )
        matched_count = sum(item.status == "matched" for item in items)
        if matched_count >= minimum:
            for index in indexes:
                item = resolved[index]
                if item.status == "missing":
                    resolved[index] = replace(
                        item,
                        status="not_required",
                        score=100.0,
                        match_method="requirement_group_satisfied",
                        deduction=0.0,
                        hard_constraint=False,
                    )
            continue
        missing_indexes = [index for index in indexes if resolved[index].status == "missing"]
        if not missing_indexes:
            continue
        representative = max(
            missing_indexes,
            key=lambda index: resolved[index].requirement.importance
            * resolved[index].requirement.specificity,
        )
        group_critical = any(resolved[index].requirement.is_critical for index in indexes)
        for index in missing_indexes:
            item = resolved[index]
            if index == representative:
                resolved[index] = replace(
                    item,
                    deduction=0.0 if group_critical else item.deduction,
                    hard_constraint=group_critical,
                )
            else:
                resolved[index] = replace(
                    item,
                    status="group_alternative_missing",
                    deduction=0.0,
                    hard_constraint=False,
                )
    return resolved


def _parse_education_requirement(value: str) -> dict[str, Any]:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    levels = sorted(
        {
            level
            for terms, level in (
                (("phd", "doctor", "博士"), 5),
                (("master", "硕士", "研究生"), 4),
                (("bachelor", "本科", "学士"), 3),
                (("associate", "大专", "专科"), 2),
                (("high school", "高中"), 1),
            )
            if any(term in text for term in terms)
        }
    )
    minimum = _minimum_education_level(text)
    accepted = [] if minimum else levels
    return {
        "accepted_levels": accepted,
        "minimum_level": minimum or None,
        "relation": "AT_LEAST" if minimum else "ANY_OF",
    }


def _minimum_education_level(text: str) -> int:
    patterns = (
        (r"(?:phd|doctor|博士)(?:研究生)?(?:学历)?\s*(?:及|或)?以上", 5),
        (r"(?:master|硕士)(?:研究生)?(?:学历)?\s*(?:及|或)?以上", 4),
        (r"(?:bachelor|本科|学士)(?:学历)?\s*(?:及|或)?以上", 3),
        (r"(?:associate|大专|专科)(?:学历)?\s*(?:及|或)?以上", 2),
        (r"(?:high school|高中)(?:学历)?\s*(?:及|或)?以上", 1),
    )
    return next((level for pattern, level in patterns if re.search(pattern, text)), 0)


def _chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    values = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    return values.get(value, 1)


def _term_present(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z]{1,3}", term):
        return bool(re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text))
    return term in text


def _required_years(value: str) -> float:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    range_match = re.search(r"(\d{1,2})\s*(?:-|~|至|到)\s*(\d{1,2})\s*(?:年|years?)", text)
    if range_match:
        return float(range_match.group(1))
    match = re.search(r"(\d{1,2})\s*(?:\+|年以上|年|years?)", text)
    return float(match.group(1)) if match else 0.0


def _candidate_years(resume: Resume, profile: ResumeProfile) -> float:
    values: list[float] = []
    current = date.today().year
    for entry in profile.experience:
        start = _year(entry.start_date or "")
        end = _year(entry.end_date or "") or (
            current if re.search(r"present|至今|现在", entry.end_date or "", re.I) else 0
        )
        if start and end >= start:
            values.append(float(end - start))
    if values:
        return min(30.0, sum(values))
    ranges = re.findall(
        r"(20\d{2})\s*(?:-|–|—|~|至|到)\s*(20\d{2}|present|至今|现在)", resume.raw_text or "", re.I
    )
    return min(
        30.0,
        sum(
            max(0, (current if not end.isdigit() else int(end)) - int(start))
            for start, end in ranges
        ),
    )


def _year(value: str) -> int:
    match = re.search(r"(?:19|20)\d{2}", value or "")
    return int(match.group()) if match else 0


def _direction_label(value: str) -> str:
    return {
        "engineering": "软件研发",
        "algorithm": "算法/模型",
        "product": "产品",
        "operations": "运营",
        "sales": "销售/商务",
        "content": "内容创作",
        "design": "设计",
        "data": "数据",
        "teaching": "教学/培训",
        "unknown": "方向待确认",
    }.get(value, value)


def _education_level(value: str) -> int:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    checks = (
        (("phd", "doctor", "博士"), 5),
        (("master", "硕士"), 4),
        (("bachelor", "本科", "学士"), 3),
        (("associate", "大专", "专科"), 2),
        (("high school", "高中"), 1),
    )
    return next((level for terms, level in checks if any(term in text for term in terms)), 0)
