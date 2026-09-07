from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.resumes import (
    ResumeAward,
    ResumeEducation,
    ResumeExperience,
    ResumeProfile,
    ResumeProject,
    ResumePublication,
)


@dataclass(frozen=True)
class ResumeSection:
    key: str
    title: str
    lines: list[str]


class HeuristicResumeExtractor:
    """Deterministic structured extractor used until an LLM provider is configured."""

    section_aliases = {
        "summary": {"summary", "profile", "objective", "about", "个人简介", "个人总结"},
        "education": {"education", "academic background", "教育经历", "教育背景"},
        "experience": {
            "experience",
            "work experience",
            "professional experience",
            "internship experience",
            "employment",
            "工作经历",
            "工作经验",
            "实习经历",
            "实习经验",
            "职业经历",
        },
        "projects": {
            "projects",
            "project experience",
            "项目经历",
            "研究与项目经历",
            "科研与项目经历",
            "项目",
        },
        "skills": {"skills", "technical skills", "技能", "专业技能", "技术栈"},
        "awards": {
            "awards",
            "honors",
            "获奖经历",
            "竞赛奖项",
            "竞赛与荣誉",
            "荣誉奖项",
            "荣誉",
        },
        "publications": {"publications", "papers", "论文", "发表"},
    }
    known_skills = (
        "Python",
        "Java",
        "Go",
        "C++",
        "SQL",
        "MySQL",
        "PostgreSQL",
        "MongoDB",
        "JavaScript",
        "TypeScript",
        "HTML",
        "CSS",
        "React",
        "Vue",
        "Next.js",
        "Node.js",
        "FastAPI",
        "Django",
        "Flask",
        "Spring Boot",
        "MyBatis",
        "Redis",
        "RabbitMQ",
        "Docker",
        "Kubernetes",
        "Linux",
        "Git",
        "Maven",
        "Pandas",
        "scikit-learn",
        "PyTorch",
        "TensorFlow",
        "LangChain",
        "LlamaIndex",
        "Dify",
        "LLM",
        "RAG",
        "MCP",
        "Agent",
        "Machine Learning",
    )
    skill_aliases = {
        "Go": ("golang",),
        "Node.js": ("nodejs", "node.js"),
        "Next.js": ("nextjs", "next.js"),
        "Spring Boot": ("springboot", "spring boot"),
        "MyBatis": ("mybatis-plus", "mybatisplus", "mybatis"),
        "RabbitMQ": ("rabbitmq",),
        "scikit-learn": ("scikit-learn", "sklearn"),
        "LangChain": ("langchain",),
        "LlamaIndex": ("llamaindex", "llama index"),
        "Machine Learning": ("machine learning", "机器学习"),
    }
    role_keywords = (
        "AI Agent Engineer",
        "Machine Learning Engineer",
        "Software Engineer",
        "Backend Engineer",
        "Data Scientist",
        "算法工程师",
        "软件工程师",
        "后端开发",
    )
    date_range_pattern = re.compile(
        r"(?P<start>(?:19|20)\d{2}[./-]\d{1,2})\s*"
        r"[-–—~至]\s*"
        r"(?P<end>(?:(?:19|20)\d{2}[./-]\d{1,2}|至今|现在|present))",
        re.IGNORECASE,
    )
    degree_pattern = re.compile(
        r"(?:博士研究生|硕士研究生|博士|硕士|本科|学士|大专|专科|Ph\.?D\.?|Master|Bachelor)",
        re.IGNORECASE,
    )

    def extract(self, raw_text: str) -> ResumeProfile:
        sections = self._sections(raw_text)
        section_map = self._section_map(sections)
        self._recover_misplaced_projects(section_map)
        full_text = raw_text.lower()

        skills = self._skills(section_map.get("skills"), full_text)
        profile = ResumeProfile(
            education=self._education(section_map.get("education")),
            skills=skills,
            projects=self._projects(section_map.get("projects"), full_text),
            experience=self._experience(section_map.get("experience")),
            awards=self._awards(section_map.get("awards")),
            publications=self._publications(section_map.get("publications")),
            target_roles=self._target_roles(full_text),
            summary=self._summary(section_map.get("summary"), raw_text),
        )
        return profile

    @staticmethod
    def _section_map(sections: list[ResumeSection]) -> dict[str, ResumeSection]:
        """Merge repeated headings instead of silently keeping only the last section."""
        grouped: dict[str, ResumeSection] = {}
        for section in sections:
            existing = grouped.get(section.key)
            if existing:
                grouped[section.key] = ResumeSection(
                    section.key,
                    existing.title,
                    [*existing.lines, *section.lines],
                )
            else:
                grouped[section.key] = section
        return grouped

    def _recover_misplaced_projects(self, sections: dict[str, ResumeSection]) -> None:
        """Recover project blocks that PDF column ordering placed below an awards heading."""
        awards = sections.get("awards")
        if not awards:
            return
        project_start = next(
            (
                index
                for index, line in enumerate(awards.lines)
                if self.date_range_pattern.search(line) and self._looks_like_project_title(line)
            ),
            None,
        )
        if project_start is None:
            return
        prefix = awards.lines[:project_start]
        first_award = next(
            (index for index, line in enumerate(prefix) if self._looks_like_award(line)),
            len(prefix),
        )
        displaced_details = prefix[:first_award]
        recovered_heading = awards.lines[project_start]
        recovered_tail = awards.lines[project_start + 1 :]
        sections["awards"] = ResumeSection("awards", awards.title, prefix[first_award:])
        existing = sections.get("projects")
        existing_lines = existing.lines if existing else []
        recovered_details: list[str] = []
        if displaced_details and existing:
            starts = [
                index
                for index, line in enumerate(existing_lines)
                if index == 0 or self._is_project_start(line, self._strip_bullet(line))
            ]
            if starts:
                last_start = starts[-1]
                recovered_details = existing_lines[last_start + 1 :]
                existing_lines = [
                    *existing_lines[: last_start + 1],
                    *displaced_details,
                ]
        project_lines = [
            recovered_heading,
            *recovered_details,
            *([] if recovered_details else displaced_details),
            *recovered_tail,
        ]
        sections["projects"] = ResumeSection(
            "projects",
            existing.title if existing else "Projects",
            [*existing_lines, *project_lines],
        )

    def split_sections(self, raw_text: str) -> list[ResumeSection]:
        return self._sections(raw_text)

    def _sections(self, raw_text: str) -> list[ResumeSection]:
        sections: list[ResumeSection] = []
        current_key = "summary"
        current_title = "Summary"
        current_lines: list[str] = []

        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading = self._heading_key(line)
            if heading:
                if current_lines:
                    sections.append(ResumeSection(current_key, current_title, current_lines))
                current_key = heading
                current_title = line.rstrip(":：")
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            sections.append(ResumeSection(current_key, current_title, current_lines))
        return sections

    def _heading_key(self, line: str) -> str | None:
        normalized = re.sub(r"[：:]$", "", line).strip().lower()
        if len(normalized) > 40 or line.startswith(("-", "•", "*", "·")):
            return None
        for key, aliases in self.section_aliases.items():
            if normalized in {alias.lower() for alias in aliases}:
                return key
        return None

    def _skills(self, section: ResumeSection | None, full_text: str) -> list[str]:
        candidates: list[str] = []
        if section:
            for line in section.lines:
                for candidate in re.split(r"[,，、|/;；]+", line.lstrip("-•*· ")):
                    clean = candidate.strip()
                    if self._is_concise_skill(clean):
                        candidates.append(clean)
        for skill in self.known_skills:
            aliases = self.skill_aliases.get(skill, (skill,))
            if any(self._contains_skill(full_text, alias) for alias in aliases):
                candidates.append(skill)
        known_by_alias = {
            alias.casefold(): skill
            for skill in self.known_skills
            for alias in self.skill_aliases.get(skill, (skill,))
        }
        normalized = [
            known_by_alias.get(candidate.casefold(), candidate) for candidate in candidates
        ]
        return self._unique_clean(normalized)

    @staticmethod
    def _contains_skill(text: str, skill: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(skill.casefold())}(?!\w)", text))

    @staticmethod
    def _is_concise_skill(value: str) -> bool:
        if (
            not value
            or len(value) > 40
            or "。" in value
            or ". " in value
            or re.search(r"[\u4e00-\u9fff]", value)
        ):
            return False
        narrative_markers = ("熟悉", "了解", "掌握", "使用", "能够", "具备", "负责", "完成")
        return not any(marker in value for marker in narrative_markers)

    def _education(self, section: ResumeSection | None) -> list[ResumeEducation]:
        if not section:
            return []
        entries = self._group_lines(section.lines, self._is_education_start)
        results: list[ResumeEducation] = []
        for entry in entries:
            heading = entry[0]
            date_match = self.date_range_pattern.search(heading)
            heading_without_date = self.date_range_pattern.sub("", heading).strip(" -|｜")
            degree_match = self.degree_pattern.search(heading_without_date)
            institution_match = re.search(
                r"[^|｜，,]{1,80}?(?:大学|学院|University|College)",
                heading_without_date,
                re.IGNORECASE,
            )
            institution = institution_match.group(0).strip() if institution_match else ""
            field = heading_without_date
            if institution:
                field = field.replace(institution, "", 1).strip(" -|｜（）()")
            if degree_match:
                field = re.sub(
                    rf"[（(]?{re.escape(degree_match.group(0))}[）)]?",
                    "",
                    field,
                    flags=re.IGNORECASE,
                ).strip(" -|｜（）()")
            details = self._unique_clean(entry[1:])
            results.append(
                ResumeEducation(
                    institution=institution,
                    degree=degree_match.group(0) if degree_match else "",
                    field=field,
                    start_date=date_match.group("start") if date_match else None,
                    end_date=date_match.group("end") if date_match else None,
                    details=details,
                )
            )
        return results

    def _experience(self, section: ResumeSection | None) -> list[ResumeExperience]:
        return self._experience_like(section, ResumeExperience)

    def _projects(self, section: ResumeSection | None, full_text: str) -> list[ResumeProject]:
        if not section:
            return []
        projects: list[ResumeProject] = []
        entries = self._group_lines(section.lines, self._is_project_start)
        for entry in entries:
            heading = entry[0]
            name = self.date_range_pattern.sub("", heading).strip(" -|｜")
            if re.search(r"\s[|｜]\s", name):
                name = re.split(r"\s[|｜]\s", name, maxsplit=1)[0].strip()
            description_lines = self._unique_clean(entry[1:])
            content = "\n".join(entry)
            technologies = self._skills(None, content.casefold())
            projects.append(
                ResumeProject(
                    name=name[:120],
                    description="\n".join(description_lines),
                    technologies=technologies,
                    highlights=description_lines,
                )
            )
        if not projects and full_text:
            return projects
        return projects

    def _group_lines(self, lines: list[str], is_start) -> list[list[str]]:
        groups: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            clean = self._strip_bullet(line)
            if not clean:
                continue
            if current and is_start(line, clean):
                groups.append(current)
                current = []
            current.append(clean)
        if current:
            groups.append(current)
        return groups

    def _is_education_start(self, raw_line: str, clean: str) -> bool:
        del raw_line
        return bool(self.date_range_pattern.search(clean))

    def _is_project_start(self, raw_line: str, clean: str) -> bool:
        if raw_line.lstrip().startswith(("-", "•", "*", "·")):
            return False
        return bool(
            self.date_range_pattern.search(clean) or re.search(r"\s[|｜]\s", clean)
        ) and self._looks_like_project_title(clean)

    @staticmethod
    def _looks_like_project_title(line: str) -> bool:
        markers = (
            "项目",
            "平台",
            "系统",
            "agent",
            "模型",
            "开发",
            "识别",
            "分析",
            "minimind",
        )
        folded = line.casefold()
        return len(line) <= 180 and any(marker in folded for marker in markers)

    @staticmethod
    def _looks_like_award(line: str) -> bool:
        markers = ("奖", "荣誉", "证书", "优秀", "竞赛", "大赛")
        return any(marker in line for marker in markers)

    def _experience_like(self, section: ResumeSection | None, model: type[ResumeExperience]):
        if not section:
            return []
        results: list[ResumeExperience] = []
        entries = self._group_lines(section.lines, self._is_experience_start)
        for entry in entries:
            heading = entry[0]
            date_match = self.date_range_pattern.search(heading)
            heading_without_date = self.date_range_pattern.sub("", heading).strip(" -|｜")
            parts = re.split(r"\s+[-|｜]\s+", heading_without_date, maxsplit=1)
            bullets = self._unique_clean(entry[1:])
            results.append(
                model(
                    company=parts[0][:120],
                    role=parts[1][:120] if len(parts) > 1 else "",
                    start_date=date_match.group("start") if date_match else None,
                    end_date=date_match.group("end") if date_match else None,
                    bullets=bullets,
                )
            )
        return results

    def _is_experience_start(self, raw_line: str, clean: str) -> bool:
        if raw_line.lstrip().startswith(("-", "•", "*", "·")):
            return False
        return bool(
            self.date_range_pattern.search(clean)
            or (len(clean) <= 180 and re.search(r"\s+[-|｜]\s+", clean))
        )

    def _awards(self, section: ResumeSection | None) -> list[ResumeAward]:
        if not section:
            return []
        return [
            ResumeAward(name=self._strip_bullet(line), details=self._strip_bullet(line))
            for line in section.lines
        ]

    def _publications(self, section: ResumeSection | None) -> list[ResumePublication]:
        if not section:
            return []
        return [
            ResumePublication(title=self._strip_bullet(line), details=self._strip_bullet(line))
            for line in section.lines
        ]

    def _summary(self, section: ResumeSection | None, raw_text: str) -> str:
        if section and section.lines:
            return " ".join(self._strip_bullet(line) for line in section.lines)
        return " ".join(raw_text.splitlines()[:3]).strip()

    def _target_roles(self, full_text: str) -> list[str]:
        return [role for role in self.role_keywords if role.lower() in full_text]

    @staticmethod
    def _strip_bullet(line: str) -> str:
        return re.sub(r"^\s*(?:[-•*·]\s*|\(?\d{1,2}[.)、]\s*)", "", line).strip()

    @staticmethod
    def _unique_clean(values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = value.strip()
            if clean and clean.lower() not in seen:
                seen.add(clean.lower())
                result.append(clean)
        return result
