from __future__ import annotations

import math
import re

from app.core.config import Settings
from app.llm.provider import LLMProvider
from app.models.entities import Job, Resume
from app.repositories.matching import MatchingRepository
from app.schemas.job_intelligence import StructuredJob
from app.schemas.matching import ResumeEvidenceRead


class ResumeRAG:
    """Retrieve and rerank only the resume chunks relevant to one JD."""

    def __init__(
        self,
        repository: MatchingRepository,
        provider: LLMProvider,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.settings = settings

    async def retrieve(self, job: Job, resume: Resume) -> list[ResumeEvidenceRead]:
        query = self.build_query(job)
        query_embedding = await self.provider.embed(query, model=self.settings.embedding_model)
        candidates = await self.repository.retrieve_resume_chunks(
            resume_id=resume.id,
            query_embedding=query_embedding,
            limit=self.settings.matching_retrieval_top_k,
        )
        query_tokens = self._tokens(query)
        evidence: list[ResumeEvidenceRead] = []
        for chunk, semantic in candidates:
            lexical = self._lexical_similarity(query_tokens, self._tokens(chunk.content))
            rerank = 0.75 * semantic + 0.25 * lexical
            evidence.append(
                ResumeEvidenceRead(
                    chunk_id=chunk.id,
                    chunk_type=chunk.chunk_type,
                    content=chunk.content,
                    metadata=chunk.chunk_metadata,
                    semantic_score=round(semantic * 100, 2),
                    rerank_score=round(rerank * 100, 2),
                )
            )
        evidence.sort(key=lambda item: item.rerank_score, reverse=True)
        return evidence[: self.settings.matching_rerank_top_k]

    @staticmethod
    def build_query(job: Job) -> str:
        normalized = job.normalized_data or {}
        profile = StructuredJob.model_validate(normalized.get("structured_job", {}))
        values = [
            f"Title: {profile.title or job.title}",
            f"Role: {profile.role_category}",
            f"Required skills: {', '.join(profile.required_skills)}",
            f"Preferred skills: {', '.join(profile.preferred_skills)}",
            f"Education: {profile.education_requirement or job.education_requirement or ''}",
            f"Experience: {profile.experience_requirement or job.experience_requirement or ''}",
            f"Responsibilities: {'; '.join(profile.responsibilities)}",
        ]
        return "\n".join(value for value in values if value.split(":", 1)[-1].strip())

    @staticmethod
    def semantic_score(evidence: list[ResumeEvidenceRead]) -> float:
        if not evidence:
            return 0.0
        top = evidence[:3]
        weighted = sum(item.semantic_score / (index + 1) for index, item in enumerate(top))
        denominator = sum(1 / (index + 1) for index in range(len(top)))
        return round(weighted / denominator, 2)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token.casefold() for token in re.findall(r"[\w+#.-]+", text) if len(token) > 1}

    @staticmethod
    def _lexical_similarity(query: set[str], content: set[str]) -> float:
        if not query or not content:
            return 0.0
        overlap = len(query & content)
        return min(1.0, overlap / math.sqrt(len(query) * len(content)))
