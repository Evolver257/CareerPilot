from __future__ import annotations

import math
import re
from uuid import UUID

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
        await self._ensure_resume_embeddings(resume)
        candidates: dict[UUID, tuple[object, float, str]] = {}
        for field, query, chunk_types in self.build_queries(job):
            query_embedding = await self.provider.embed(
                query, model=self.settings.embedding_model
            )
            for chunk, semantic in await self.repository.retrieve_resume_chunks(
                resume_id=resume.id,
                query_embedding=query_embedding,
                limit=self.settings.matching_retrieval_top_k,
                chunk_types=chunk_types,
            ):
                previous = candidates.get(chunk.id)
                if previous is None or semantic > previous[1]:
                    candidates[chunk.id] = (chunk, semantic, field)

        evidence: list[ResumeEvidenceRead] = []
        for chunk, semantic, field in candidates.values():
            query_tokens = self._tokens(self._query_for_field(job, field))
            lexical = self._lexical_similarity(query_tokens, self._tokens(chunk.content))
            # Hybrid reranking prevents a good exact skill match from being
            # discarded by an imperfect embedding while keeping dense retrieval
            # as the dominant signal.
            rerank = 0.65 * semantic + 0.35 * lexical
            metadata = {**(chunk.chunk_metadata or {}), "retrieval_field": field}
            evidence.append(
                ResumeEvidenceRead(
                    chunk_id=chunk.id,
                    chunk_type=chunk.chunk_type,
                    content=chunk.content,
                    metadata=metadata,
                    semantic_score=round(semantic * 100, 2),
                    rerank_score=round(rerank * 100, 2),
                )
            )
        evidence.sort(key=lambda item: item.rerank_score, reverse=True)
        return evidence[: self.settings.matching_rerank_top_k]

    async def _ensure_resume_embeddings(self, resume: Resume) -> None:
        expected_signature = getattr(
            self.provider, "embedding_signature", self.settings.embedding_model
        )
        stale_chunks = [
            chunk
            for chunk in resume.chunks
            if len(chunk.embedding or []) != self.settings.embedding_dimensions
            or (chunk.chunk_metadata or {}).get("embedding_signature") != expected_signature
        ]
        if not stale_chunks:
            return
        for chunk in stale_chunks:
            chunk.embedding = await self.provider.embed(
                chunk.content, model=self.settings.embedding_model
            )
            chunk.chunk_metadata = {
                **(chunk.chunk_metadata or {}),
                "embedding_signature": expected_signature,
                "embedding_dimensions": len(chunk.embedding),
            }
        await self.repository.session.commit()

    @classmethod
    def build_queries(cls, job: Job) -> list[tuple[str, str, tuple[str, ...]]]:
        normalized = job.normalized_data or {}
        profile = StructuredJob.model_validate(normalized.get("structured_job", {}))
        skills = ", ".join([*profile.required_skills, *profile.preferred_skills])
        responsibilities = "; ".join(profile.responsibilities)
        queries: list[tuple[str, str, tuple[str, ...]]] = []
        if skills:
            queries.append(
                (
                    "skills",
                    "\n".join(
                        value
                        for value in (
                            f"Title: {profile.title or job.title}",
                            f"Role: {profile.role_category}",
                            f"Skills: {skills}",
                        )
                        if value.split(":", 1)[-1].strip()
                    ),
                    ("skill", "project", "experience", "summary"),
                )
            )
        if responsibilities or profile.experience_requirement or job.experience_requirement:
            queries.append(
                (
                    "responsibilities",
                    "\n".join(
                        value
                        for value in (
                            f"Role: {profile.role_category}",
                            "Experience: "
                            f"{profile.experience_requirement or job.experience_requirement or ''}",
                            f"Responsibilities: {responsibilities}",
                        )
                        if value.split(":", 1)[-1].strip()
                    ),
                    ("experience", "project", "summary"),
                )
            )
        education = profile.education_requirement or job.education_requirement or ""
        if education:
            queries.append(("education", f"Education: {education}", ("education",)))
        if not queries:
            queries.append(("general", cls.build_query(job), ()))
        return queries

    @classmethod
    def _query_for_field(cls, job: Job, field: str) -> str:
        for query_field, query, _ in cls.build_queries(job):
            if query_field == field:
                return query
        return cls.build_query(job)

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
        # Keep the persisted field name for API compatibility, but aggregate
        # the hybrid rerank score so lexical evidence is not thrown away after
        # retrieval.
        weighted = sum(item.rerank_score / (index + 1) for index, item in enumerate(top))
        denominator = sum(1 / (index + 1) for index in range(len(top)))
        return round(weighted / denominator, 2)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        normalized = re.sub(r"\s+", "", text.casefold())
        tokens = {
            token
            for token in re.findall(r"[a-z0-9][a-z0-9+#._/-]*", normalized)
            if len(token) > 1
        }
        for segment in re.findall(r"[\u3400-\u9fff]+", normalized):
            tokens.update(
                f"zh2:{segment[index:index + 2]}" for index in range(len(segment) - 1)
            )
            if len(segment) >= 3:
                tokens.update(
                    f"zh3:{segment[index:index + 3]}"
                    for index in range(len(segment) - 2)
                )
        return tokens

    @staticmethod
    def _lexical_similarity(query: set[str], content: set[str]) -> float:
        if not query or not content:
            return 0.0
        overlap = len(query & content)
        return min(1.0, overlap / math.sqrt(len(query) * len(content)))
