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
            "employment",
            "工作经历",
            "实习经历",
        },
        "projects": {"projects", "project experience", "项目经历", "项目"},
        "skills": {"skills", "technical skills", "技能", "专业技能", "技术栈"},
        "awards": {"awards", "honors", "获奖经历", "荣誉"},
        "publications": {"publications", "papers", "论文", "发表"},
    }
    known_skills = (
        "Python",
        "Java",
        "C++",
        "SQL",
        "JavaScript",
        "TypeScript",
        "React",
        "Next.js",
        "FastAPI",
        "Django",
        "Flask",
        "PostgreSQL",
        "Redis",
        "Docker",
        "Kubernetes",
        "Git",
        "PyTorch",
        "TensorFlow",
        "LLM",
        "RAG",
        "MCP",
        "Agent",
        "Machine Learning",
    )
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

    def extract(self, raw_text: str) -> ResumeProfile:
        sections = self._sections(raw_text)
        section_map = {section.key: section for section in sections}
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
                candidates.extend(re.split(r"[,，、|/;；]+", line.lstrip("-•*· ")))
        for skill in self.known_skills:
            if re.search(rf"(?<!\w){re.escape(skill.lower())}(?!\w)", full_text):
                candidates.append(skill)
        return self._unique_clean(candidates)

    def _education(self, section: ResumeSection | None) -> list[ResumeEducation]:
        if not section:
            return []
        return [
            ResumeEducation(
                institution=self._strip_bullet(line), details=[self._strip_bullet(line)]
            )
            for line in section.lines
        ]

    def _experience(self, section: ResumeSection | None) -> list[ResumeExperience]:
        return self._experience_like(section, ResumeExperience)

    def _projects(self, section: ResumeSection | None, full_text: str) -> list[ResumeProject]:
        if not section:
            return []
        projects: list[ResumeProject] = []
        for line in section.lines:
            clean = self._strip_bullet(line)
            technologies = [skill for skill in self.known_skills if skill.lower() in clean.lower()]
            projects.append(
                ResumeProject(
                    name=clean[:120],
                    description=clean,
                    technologies=self._unique_clean(technologies),
                )
            )
        if not projects and full_text:
            return projects
        return projects

    def _experience_like(self, section: ResumeSection | None, model: type[ResumeExperience]):
        if not section:
            return []
        results: list[ResumeExperience] = []
        for line in section.lines:
            clean = self._strip_bullet(line)
            parts = re.split(r"\s+[-|｜]\s+", clean, maxsplit=1)
            results.append(
                model(
                    company=parts[0][:120],
                    role=parts[1][:120] if len(parts) > 1 else "",
                    bullets=[clean],
                )
            )
        return results

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
        return re.sub(r"^[-•*·\d.)\s]+", "", line).strip()

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
