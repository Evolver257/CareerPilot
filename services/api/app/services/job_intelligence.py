from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.schemas.job_intelligence import (
    JobRequirements,
    JobSalary,
    StructuredJob,
)


@dataclass(frozen=True)
class ParsedJob:
    raw_text: str
    sections: dict[str, list[str]]


@dataclass(frozen=True)
class JobSkillDraft:
    name: str
    skill_type: str
    importance: float
    confidence: float = 0.9


@dataclass(frozen=True)
class JobAnalysis:
    structured_job: StructuredJob
    requirements: JobRequirements
    skills: list[JobSkillDraft]
    content_hash: str


class JobParser:
    """Normalize raw JD text and split common requirement sections."""

    section_aliases = {
        "requirements": {
            "requirements",
            "qualifications",
            "what you bring",
            "任职要求",
            "岗位要求",
            "职位要求",
            "资格要求",
        },
        "preferred": {
            "preferred qualifications",
            "nice to have",
            "bonus points",
            "加分项",
            "优先条件",
        },
        "responsibilities": {
            "responsibilities",
            "what you will do",
            "岗位职责",
            "工作职责",
            "工作内容",
        },
        "summary": {"summary", "about the role", "职位简介", "岗位简介", "职位描述"},
        "skills": {"skills", "technical skills", "技能要求", "技术栈"},
    }

    def parse(self, raw_jd: str) -> ParsedJob:
        text = self._normalize(raw_jd)
        sections: dict[str, list[str]] = {"body": []}
        current = "body"
        for line in text.splitlines():
            heading = self._heading_type(line)
            if heading:
                current = heading
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)
        return ParsedJob(raw_text=text, sections=sections)

    @staticmethod
    def _normalize(raw_jd: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw_jd.splitlines()]
        return "\n".join(line for line in lines if line)

    def _heading_type(self, line: str) -> str | None:
        cleaned = line.strip(" #:：-—")
        normalized = cleaned.casefold()
        for section, aliases in self.section_aliases.items():
            if normalized in aliases:
                return section
        return None


class SkillExtractor:
    known_skills = (
        "Python",
        "FastAPI",
        "Django",
        "Flask",
        "Java",
        "Spring Boot",
        "Go",
        "Golang",
        "Rust",
        "JavaScript",
        "TypeScript",
        "React",
        "Next.js",
        "Vue",
        "Node.js",
        "HTML",
        "CSS",
        "SQL",
        "PostgreSQL",
        "MySQL",
        "Redis",
        "MongoDB",
        "Docker",
        "Kubernetes",
        "AWS",
        "Azure",
        "GCP",
        "Terraform",
        "Git",
        "Linux",
        "Kafka",
        "Spark",
        "Airflow",
        "Machine Learning",
        "Deep Learning",
        "NLP",
        "LLM",
        "RAG",
        "PyTorch",
        "TensorFlow",
        "scikit-learn",
        "Pandas",
        "Figma",
        "Product Management",
        "自动化测试",
    )

    def extract(self, parsed: ParsedJob) -> list[JobSkillDraft]:
        required_text = "\n".join(
            line
            for section in ("body", "requirements", "skills")
            for line in parsed.sections.get(section, [])
        )
        preferred_text = "\n".join(parsed.sections.get("preferred", []))
        drafts: list[JobSkillDraft] = []
        for skill in self.known_skills:
            pattern = self._pattern(skill)
            in_preferred = bool(re.search(pattern, preferred_text, flags=re.IGNORECASE))
            in_required = bool(re.search(pattern, required_text, flags=re.IGNORECASE))
            if not in_preferred and not in_required:
                continue
            skill_type = "preferred" if in_preferred and not in_required else "required"
            importance = 0.7 if skill_type == "required" else 0.4
            drafts.append(JobSkillDraft(skill, skill_type, importance))
        return drafts

    @staticmethod
    def _pattern(skill: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9+.# -]+", skill):
            return rf"(?<![A-Za-z0-9]){re.escape(skill)}(?![A-Za-z0-9])"
        return re.escape(skill)


class RequirementExtractor:
    education_pattern = re.compile(
        r"[^\n]*(?:bachelor|master|phd|degree|本科|硕士|博士|学士)[^\n]*",
        flags=re.IGNORECASE,
    )
    experience_pattern = re.compile(
        r"[^\n]*(?:\d+\+?\s*(?:years?|年)|经验)[^\n]*",
        flags=re.IGNORECASE,
    )

    def extract(self, parsed: ParsedJob) -> JobRequirements:
        all_lines = self._unique_lines(
            parsed.sections.get("requirements", []) + parsed.sections.get("body", [])
        )
        education = self._first_match(self.education_pattern, all_lines)
        experience = self._first_match(self.experience_pattern, all_lines)
        responsibilities = self._bullets(parsed.sections.get("responsibilities", []))
        if not responsibilities:
            responsibilities = self._bullets(parsed.sections.get("body", []))
        return JobRequirements(
            education=education,
            experience=experience,
            responsibilities=responsibilities[:12],
        )

    @staticmethod
    def _unique_lines(lines: list[str]) -> list[str]:
        return list(dict.fromkeys(line for line in lines if line))

    @staticmethod
    def _first_match(pattern: re.Pattern[str], lines: list[str]) -> str:
        for line in lines:
            if pattern.search(line):
                return line.lstrip("-•* ")
        return ""

    @staticmethod
    def _bullets(lines: list[str]) -> list[str]:
        return [
            line.lstrip("-•* ")
            for line in lines
            if line.startswith(("-", "•", "*")) and len(line.lstrip("-•* ")) > 4
        ]


class JobNormalizer:
    def __init__(
        self,
        parser: JobParser | None = None,
        skill_extractor: SkillExtractor | None = None,
        requirement_extractor: RequirementExtractor | None = None,
    ) -> None:
        self.parser = parser or JobParser()
        self.skill_extractor = skill_extractor or SkillExtractor()
        self.requirement_extractor = requirement_extractor or RequirementExtractor()

    def analyze(self, raw_jd: str, *, title_hint: str | None = None) -> JobAnalysis:
        parsed = self.parser.parse(raw_jd)
        requirements = self.requirement_extractor.extract(parsed)
        skills = self.skill_extractor.extract(parsed)
        title = title_hint or self._title(parsed)
        profile = StructuredJob(
            title=title,
            role_category=self._role_category(title, parsed.raw_text),
            level=self._level(title, parsed.raw_text),
            job_type=self._job_type(parsed.raw_text),
            location=self._location(parsed.raw_text),
            salary=self._salary(parsed.raw_text),
            required_skills=[skill.name for skill in skills if skill.skill_type == "required"],
            preferred_skills=[skill.name for skill in skills if skill.skill_type == "preferred"],
            education_requirement=requirements.education,
            experience_requirement=requirements.experience,
            responsibilities=requirements.responsibilities,
            keywords=self._keywords(title, skills),
            summary=self._summary(parsed),
        )
        return JobAnalysis(
            structured_job=profile,
            requirements=requirements,
            skills=skills,
            content_hash=hashlib.sha256(parsed.raw_text.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _title(parsed: ParsedJob) -> str:
        for line in parsed.raw_text.splitlines():
            if line.casefold() not in JobParser.section_aliases and len(line) <= 160:
                return line.lstrip("# ")
        return "Untitled Job"

    @staticmethod
    def _role_category(title: str, text: str) -> str:
        haystack = f"{title} {text}".casefold()
        categories = (
            (("backend", "后端", "api"), "Backend Engineering"),
            (("frontend", "前端", "react", "vue"), "Frontend Engineering"),
            (("data", "数据", "spark", "airflow"), "Data Engineering"),
            (("machine learning", "ml engineer", "算法", "机器学习"), "Machine Learning"),
            (("devops", "sre", "platform", "云"), "DevOps / Platform"),
            (("product", "产品"), "Product"),
            (("design", "设计", "ux", "ui"), "Design"),
            (("qa", "quality", "测试", "test automation"), "Quality Engineering"),
            (("mobile", "ios", "android"), "Mobile Engineering"),
            (("security", "安全"), "Security"),
        )
        for keywords, category in categories:
            if any(keyword in haystack for keyword in keywords):
                return category
        return "General"

    @staticmethod
    def _level(title: str, text: str) -> str:
        haystack = f"{title} {text}".casefold()
        for keywords, level in (
            (("intern", "实习"), "Intern"),
            (("junior", "初级"), "Junior"),
            (("senior", "高级"), "Senior"),
            (("lead", "负责人"), "Lead"),
            (("manager", "经理"), "Manager"),
        ):
            if any(keyword in haystack for keyword in keywords):
                return level
        return "Mid-level"

    @staticmethod
    def _job_type(text: str) -> str:
        haystack = text.casefold()
        if "intern" in haystack or "实习" in haystack:
            return "Internship"
        if "contract" in haystack or "合同" in haystack:
            return "Contract"
        if "part-time" in haystack or "兼职" in haystack:
            return "Part-time"
        return "Full-time"

    @staticmethod
    def _location(text: str) -> str:
        for location in (
            "Remote",
            "Shanghai",
            "Beijing",
            "Shenzhen",
            "Hangzhou",
            "Guangzhou",
            "New York",
        ):
            if location.casefold() in text.casefold() or location in text:
                return location
        return ""

    @staticmethod
    def _salary(text: str) -> JobSalary:
        match = re.search(
            r"(?:薪资|salary)?[^\n$¥￥]*[$¥￥]?\s*(\d{2,3})\s*[kK]?\s*[-–~至]\s*[$¥￥]?\s*(\d{2,3})\s*[kK]?",
            text,
        )
        if not match:
            return JobSalary()
        minimum, maximum = (int(value) for value in match.groups())
        return JobSalary(
            minimum=minimum, maximum=maximum, currency="USD" if "$" in match.group(0) else "CNY"
        )

    @staticmethod
    def _summary(parsed: ParsedJob) -> str:
        summary_lines = parsed.sections.get("summary", [])
        if summary_lines:
            return " ".join(summary_lines[:3])
        body = parsed.sections.get("body", [])
        return " ".join(body[:2])

    @staticmethod
    def _keywords(title: str, skills: list[JobSkillDraft]) -> list[str]:
        values = [title, *[skill.name for skill in skills]]
        return list(dict.fromkeys(value for value in values if value))[:20]
