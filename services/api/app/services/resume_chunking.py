from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.llm.tokenization import (
    APPROXIMATE_TOKEN_COUNTER,
    TokenCounter,
    max_prefix_end,
)
from app.schemas.resumes import ResumeProfile
from app.services.resume_extraction import HeuristicResumeExtractor

RESUME_CHUNKING_VERSION = "RESUME_SEMANTIC_V3_QWEN_TOKENS"


@dataclass(frozen=True)
class ResumeChunkDraft:
    chunk_type: str
    content: str
    metadata: dict[str, object]


class ResumeSemanticChunker:
    """Section-aware chunker that keeps resume evidence small and traceable."""

    def __init__(
        self,
        *,
        chunk_size: int = 600,
        overlap: int = 80,
        token_limit: int = 384,
        token_overlap: int = 48,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.token_limit = token_limit
        self.token_overlap = token_overlap
        self.token_counter = token_counter or APPROXIMATE_TOKEN_COUNTER
        self.extractor = HeuristicResumeExtractor()

    def chunk(self, raw_text: str, profile: ResumeProfile) -> list[ResumeChunkDraft]:
        sections = self._profile_sections(profile)
        # Preserve an experience section even when its entries cannot be
        # structured (for example, a PDF column layout without date ranges).
        # Dropping it makes the most important JD evidence unavailable to RAG.
        if not profile.experience:
            for section in self.extractor.split_sections(raw_text):
                if section.key == "experience" and section.lines:
                    sections.append(("experience", 0, "\n".join(section.lines), "raw_section"))
        if not sections:
            sections = [("summary", 0, raw_text, "raw_text")]

        drafts: list[ResumeChunkDraft] = []
        for section_name, item_index, content, source in sections:
            for part_index, part in enumerate(self._split(content)):
                drafts.append(
                    ResumeChunkDraft(
                        chunk_type=section_name,
                        content=part,
                        metadata={
                            "source": source,
                            "section": section_name,
                            "item_index": item_index,
                            "part_index": part_index,
                            "chunking_version": RESUME_CHUNKING_VERSION,
                            "content_hash": hashlib.sha256(part.encode("utf-8")).hexdigest(),
                            "token_count": self.token_counter.count(part),
                            "tokenizer_signature": self.token_counter.signature,
                            "token_count_exact": self.token_counter.exact,
                        },
                    )
                )
        return drafts

    def _profile_sections(self, profile: ResumeProfile) -> list[tuple[str, int, str, str]]:
        sections: list[tuple[str, int, str, str]] = []
        if profile.summary:
            sections.append(("summary", 0, profile.summary, "structured_profile"))
        sections.extend(self._entry_sections("education", profile.education))
        sections.extend(self._entry_sections("experience", profile.experience))
        sections.extend(self._entry_sections("project", profile.projects))
        if profile.skills:
            sections.append(
                ("skill", 0, "skills: " + ", ".join(profile.skills), "structured_profile")
            )
        sections.extend(self._entry_sections("award", profile.awards))
        sections.extend(self._entry_sections("publication", profile.publications))
        if profile.target_roles:
            sections.append(
                (
                    "target_role",
                    0,
                    "target_roles: " + ", ".join(profile.target_roles),
                    "structured_profile",
                )
            )
        return sections

    def _entry_sections(
        self, section_name: str, entries: list[object]
    ) -> list[tuple[str, int, str, str]]:
        sections: list[tuple[str, int, str, str]] = []
        for item_index, entry in enumerate(entries):
            rendered = self._dump_entry(entry)
            if rendered:
                sections.append((section_name, item_index, rendered, "structured_profile"))
        return sections

    @staticmethod
    def _dump_entry(entry: object) -> str:
        values = entry.model_dump(exclude_none=True)
        rendered: list[str] = []
        seen: set[str] = set()
        for key, value in values.items():
            if not value:
                continue
            items = value if isinstance(value, list) else [value]
            clean_items = [str(item).strip() for item in items if str(item).strip()]
            if not clean_items:
                continue
            text = "；".join(clean_items)
            normalized = text.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            rendered.append(f"{key}: {text}")
        return "\n".join(rendered)

    def _split(self, content: str) -> list[str]:
        content = content.strip()
        if not content:
            return []
        if self._fits(content):
            return [content]

        lines = content.splitlines()
        prefix = lines[0].strip() if len(lines) > 1 and len(lines[0]) <= 160 else ""
        body = "\n".join(lines[1:]).strip() if prefix else content
        char_budget = self.chunk_size - len(prefix) - 1 if prefix else self.chunk_size
        prefix_tokens = self.token_counter.count(f"{prefix}\n") if prefix else 0
        token_budget = self.token_limit - prefix_tokens
        if char_budget <= self.overlap + 20 or token_budget <= self.token_overlap + 8:
            prefix = ""
            body = content
            char_budget = self.chunk_size
            token_budget = self.token_limit

        parts: list[str] = []
        start = 0
        while start < len(body):
            end = start + max_prefix_end(
                body[start:],
                max_chars=char_budget,
                max_tokens=token_budget,
                counter=self.token_counter,
            )
            if end < len(body):
                search_from = start + max(1, int((end - start) * 0.55))
                boundary = max(body.rfind(mark, search_from, end) for mark in "\n。！？；;,.，")
                if boundary >= search_from:
                    end = boundary + 1
            body_part = body[start:end].strip()
            part = f"{prefix}\n{body_part}".strip() if prefix else body_part
            if part:
                parts.append(part)
            if end == len(body):
                break
            start = self._overlap_start(body, start, end)
        return parts

    def _fits(self, content: str) -> bool:
        return (
            len(content) <= self.chunk_size
            and self.token_counter.count(content) <= self.token_limit
        )

    def _overlap_start(self, body: str, previous_start: int, end: int) -> int:
        start = max(previous_start + 1, end - self.overlap)
        # Keep overlap bounded in both characters and model tokens. Moving the
        # start forward preserves the original text exactly.
        while (
            start < end
            and self.token_counter.count(body[start:end]) > self.token_overlap
        ):
            start += 1
        return start
