from __future__ import annotations

from dataclasses import dataclass

from app.schemas.resumes import ResumeProfile
from app.services.resume_extraction import HeuristicResumeExtractor


@dataclass(frozen=True)
class ResumeChunkDraft:
    chunk_type: str
    content: str
    metadata: dict[str, object]


class ResumeSemanticChunker:
    """Section-aware chunker that keeps resume evidence small and traceable."""

    def __init__(self, *, chunk_size: int = 1200, overlap: int = 150) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.extractor = HeuristicResumeExtractor()

    def chunk(self, raw_text: str, profile: ResumeProfile) -> list[ResumeChunkDraft]:
        sections = self._profile_sections(profile)
        if not sections:
            sections = [("summary", raw_text)]

        drafts: list[ResumeChunkDraft] = []
        for section_name, content in sections:
            for part_index, part in enumerate(self._split(content)):
                drafts.append(
                    ResumeChunkDraft(
                        chunk_type=section_name,
                        content=part,
                        metadata={
                            "source": "structured_profile",
                            "section": section_name,
                            "part_index": part_index,
                        },
                    )
                )
        return drafts

    def _profile_sections(self, profile: ResumeProfile) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        if profile.summary:
            sections.append(("summary", profile.summary))
        if profile.education:
            sections.append(("education", self._dump_entries(profile.education)))
        if profile.experience:
            sections.append(("experience", self._dump_entries(profile.experience)))
        if profile.projects:
            sections.append(("project", self._dump_entries(profile.projects)))
        if profile.skills:
            sections.append(("skill", "Skills: " + ", ".join(profile.skills)))
        if profile.awards:
            sections.append(("award", self._dump_entries(profile.awards)))
        if profile.publications:
            sections.append(("publication", self._dump_entries(profile.publications)))
        return sections

    @staticmethod
    def _dump_entries(entries: list[object]) -> str:
        lines: list[str] = []
        for entry in entries:
            values = entry.model_dump(exclude_none=True)
            lines.append("; ".join(f"{key}: {value}" for key, value in values.items() if value))
        return "\n".join(lines)

    def _split(self, content: str) -> list[str]:
        if len(content) <= self.chunk_size:
            return [content]
        parts: list[str] = []
        start = 0
        while start < len(content):
            end = min(start + self.chunk_size, len(content))
            part = content[start:end].strip()
            if part:
                parts.append(part)
            if end == len(content):
                break
            start = max(end - self.overlap, start + 1)
        return parts
