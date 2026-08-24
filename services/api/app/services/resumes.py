from __future__ import annotations

from pathlib import PurePath
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.llm.provider import LLMProvider
from app.models.entities import Resume, ResumeChunk, User
from app.repositories.resumes import ResumeRepository
from app.services.resume_chunking import ResumeChunkDraft, ResumeSemanticChunker
from app.services.resume_extraction import HeuristicResumeExtractor
from app.services.resume_parsing import ResumeFileParser


class ResumeNotFoundError(ValueError):
    """Raised when a requested resume does not exist."""


class ResumeUserNotFoundError(ValueError):
    """Raised when a caller references an unknown user."""


class ResumeService:
    def __init__(self, session: AsyncSession, embedding_provider: LLMProvider) -> None:
        self.session = session
        self.repository = ResumeRepository(session)
        self.embedding_provider = embedding_provider
        self.file_parser = ResumeFileParser()
        self.extractor = HeuristicResumeExtractor()
        self.chunker = ResumeSemanticChunker()
        self.settings = get_settings()

    async def upload(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        data: bytes,
        name: str | None,
        user_id: UUID | None,
    ) -> Resume:
        parsed = self.file_parser.parse(filename=filename, content_type=content_type, data=data)
        user = await self._resolve_user(user_id)
        profile = self.extractor.extract(parsed.raw_text)
        drafts = self.chunker.chunk(parsed.raw_text, profile)
        resume = Resume(
            user_id=user.id,
            name=(name or PurePath(parsed.filename).stem)[:200],
            original_filename=parsed.filename,
            raw_text=parsed.raw_text,
            structured_profile=profile.model_dump(),
            version=1,
            is_default=not await self._has_resume(user.id),
        )
        return await self._persist_resume(resume, drafts)

    async def list_resumes(self, *, user_id: UUID | None) -> tuple[list[Resume], int]:
        return await self.repository.list(user_id=user_id)

    async def get_resume(self, resume_id: UUID) -> Resume:
        resume = await self.repository.get(resume_id)
        if resume is None:
            raise ResumeNotFoundError("Resume not found")
        return resume

    async def get_chunks(self, resume_id: UUID) -> list[ResumeChunk]:
        resume = await self.repository.get(resume_id)
        if resume is None:
            raise ResumeNotFoundError("Resume not found")
        return await self.repository.get_chunks(resume_id)

    async def parse_existing(self, resume_id: UUID) -> Resume:
        resume = await self.get_resume(resume_id)
        profile = self.extractor.extract(resume.raw_text)
        drafts = self.chunker.chunk(resume.raw_text, profile)
        resume.structured_profile = profile.model_dump()
        await self.session.execute(delete(ResumeChunk).where(ResumeChunk.resume_id == resume.id))
        return await self._persist_chunks(resume, drafts)

    async def _persist_resume(self, resume: Resume, drafts: list[ResumeChunkDraft]) -> Resume:
        self.session.add(resume)
        await self.session.flush()
        return await self._persist_chunks(resume, drafts)

    async def _persist_chunks(self, resume: Resume, drafts: list[ResumeChunkDraft]) -> Resume:
        chunks: list[ResumeChunk] = []
        for draft in drafts:
            embedding = await self.embedding_provider.embed(
                draft.content, model=self.settings.embedding_model
            )
            chunks.append(
                ResumeChunk(
                    resume_id=resume.id,
                    chunk_type=draft.chunk_type,
                    content=draft.content,
                    chunk_metadata=draft.metadata,
                    embedding=embedding,
                )
            )
        self.session.add_all(chunks)
        await self.session.commit()
        refreshed = await self.repository.get(resume.id)
        if refreshed is None:
            raise ResumeNotFoundError("Resume disappeared during persistence")
        return refreshed

    async def _resolve_user(self, user_id: UUID | None) -> User:
        if user_id:
            user = await self.session.get(User, user_id)
            if user is None:
                raise ResumeUserNotFoundError("User not found")
            return user

        user = await self.session.scalar(
            select(User).where(User.email == self.settings.default_user_email)
        )
        if user:
            return user
        user = User(email=self.settings.default_user_email, name=self.settings.default_user_name)
        self.session.add(user)
        await self.session.flush()
        return user

    async def _has_resume(self, user_id: UUID) -> bool:
        return bool(
            await self.session.scalar(select(Resume.id).where(Resume.user_id == user_id).limit(1))
        )


def resume_chunk_embedding_dimensions(chunk: ResumeChunk) -> int:
    return len(chunk.embedding or [])
