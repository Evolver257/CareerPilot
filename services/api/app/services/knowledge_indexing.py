from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.llm.provider import LLMProvider, embed_texts
from app.llm.tokenization import token_counter_for_provider
from app.models.entities import (
    Job,
    JobKnowledgeChunk,
    JobKnowledgeDocument,
    JobSkillFact,
    JobVersion,
    KnowledgeIndexRun,
    KnowledgeIndexRunItem,
    SkillAlias,
    SkillTaxonomy,
)
from app.models.work import BackgroundWork
from app.schemas.knowledge import KnowledgeIndexRunCreate
from app.services.job_knowledge import (
    JOB_KNOWLEDGE_PARSER_VERSION,
    JOB_KNOWLEDGE_VERSION,
    build_job_knowledge_chunks,
    canonicalize_skill,
    normalize_experience_requirement,
    normalize_skill_name,
    skill_category,
)
from app.services.job_knowledge_rag import clear_knowledge_search_cache
from app.services.work_queue import enqueue_work

KNOWLEDGE_INDEX_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}
class KnowledgeIndexNotFoundError(ValueError):
    pass


class KnowledgeIndexActionError(ValueError):
    pass


class KnowledgeIndexJobError(ValueError):
    pass


@dataclass(frozen=True)
class IndexedJobResult:
    skipped: bool
    chunk_count: int
    reused_embedding_count: int


def _now() -> datetime:
    return datetime.now(UTC)


def _job_content_hash(job: Job) -> str:
    if job.content_hash:
        return job.content_hash
    return hashlib.sha256((job.description or "").encode("utf-8")).hexdigest()


def _salary_unit(job: Job) -> str:
    raw = job.raw_data or {}
    value = " ".join(str(raw.get(key) or "") for key in ("salary_text", "salary", "salaryText"))
    lowered = value.lower()
    if "天" in value or "daily" in lowered:
        return "cny_day"
    if "年" in value and ("万" in value or "w" in lowered):
        return "cny_year_wan"
    if "k" in lowered or "月" in value:
        return "cny_month_k"
    return ""


def _structured_job(job: Job) -> dict[str, Any]:
    return (job.normalized_data or {}).get("structured_job") or {}


def _normalized_experience(job: Job, structured: dict[str, Any]) -> str:
    for candidate in (
        structured.get("experience_requirement"),
        job.experience_requirement,
    ):
        normalized = normalize_experience_requirement(str(candidate or ""))
        if normalized:
            return normalized
    return ""


def _embedding_signature(provider: LLMProvider, settings: Settings) -> str:
    dimensions = int(getattr(provider, "dimensions", settings.embedding_dimensions))
    if dimensions != settings.embedding_dimensions:
        raise KnowledgeIndexJobError(
            "岗位知识库向量维度不匹配；"
            f"当前配置为 {settings.embedding_dimensions}，Provider 为 {dimensions}。"
        )
    signature = str(getattr(provider, "embedding_signature", "") or "")
    if not signature:
        signature = (
            f"{getattr(provider, 'provider_name', 'unknown')}:"
            f"{getattr(provider, 'embedding_model', getattr(provider, 'model', 'unknown'))}:"
            f"{dimensions}"
        )
    return signature


class KnowledgeIndexService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: LLMProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.settings = settings or get_settings()

    async def list_runs(self) -> tuple[list[KnowledgeIndexRun], int]:
        total = await self.session.scalar(select(func.count(KnowledgeIndexRun.id))) or 0
        runs = list(
            (
                await self.session.scalars(
                    select(KnowledgeIndexRun)
                    .order_by(KnowledgeIndexRun.created_at.desc())
                    .limit(100)
                )
            ).all()
        )
        return runs, int(total)

    async def health(self) -> dict[str, Any]:
        documents, indexed, updated = (
            await self.session.execute(
                select(
                    func.count(JobKnowledgeDocument.id),
                    func.count(func.distinct(JobKnowledgeDocument.job_id)),
                    func.max(JobKnowledgeDocument.updated_at),
                ).where(JobKnowledgeDocument.active.is_(True))
            )
        ).one()
        chunks = (
            await self.session.scalar(
                select(func.count(JobKnowledgeChunk.id))
                .join(JobKnowledgeDocument)
                .where(JobKnowledgeDocument.active.is_(True))
            )
            or 0
        )
        vector_conditions = [
            JobKnowledgeDocument.active.is_(True),
            JobKnowledgeChunk.embedding.is_not(None),
            JobKnowledgeChunk.embedding_dimensions == self.settings.embedding_dimensions,
        ]
        signature = str(getattr(self.embedding_provider, "embedding_signature", "") or "")
        if signature:
            vector_conditions.append(JobKnowledgeChunk.embedding_signature == signature)
        embedded_chunks = (
            await self.session.scalar(
                select(func.count(JobKnowledgeChunk.id))
                .join(JobKnowledgeDocument)
                .where(*vector_conditions)
            )
            or 0
        )
        jobs_total = await self.session.scalar(select(func.count(Job.id))) or 0
        chunk_is_compatible = and_(
            JobKnowledgeChunk.embedding.is_not(None),
            JobKnowledgeChunk.embedding_dimensions == self.settings.embedding_dimensions,
        )
        if signature:
            chunk_is_compatible = and_(
                chunk_is_compatible,
                JobKnowledgeChunk.embedding_signature == signature,
            )
        coverage_rows = (
            await self.session.execute(
                select(
                    Job.id.label("job_id"),
                    Job.content_hash.label("job_content_hash"),
                    JobKnowledgeDocument.id.label("document_id"),
                    JobKnowledgeDocument.current_embedding_signature,
                    JobKnowledgeDocument.knowledge_version,
                    JobVersion.content_hash.label("version_content_hash"),
                    func.count(JobKnowledgeChunk.id).label("document_chunk_count"),
                    func.sum(case((chunk_is_compatible, 0), else_=1)).label(
                        "incompatible_chunk_count"
                    ),
                )
                .select_from(Job)
                .outerjoin(
                    JobKnowledgeDocument,
                    and_(
                        JobKnowledgeDocument.job_id == Job.id,
                        JobKnowledgeDocument.active.is_(True),
                    ),
                )
                .outerjoin(JobVersion, JobVersion.id == JobKnowledgeDocument.job_version_id)
                .outerjoin(
                    JobKnowledgeChunk,
                    JobKnowledgeChunk.document_id == JobKnowledgeDocument.id,
                )
                .group_by(
                    Job.id,
                    Job.content_hash,
                    JobKnowledgeDocument.id,
                    JobKnowledgeDocument.current_embedding_signature,
                    JobKnowledgeDocument.knowledge_version,
                    JobVersion.content_hash,
                )
            )
        ).all()
        indexed_job_ids: set[UUID] = set()
        compatible_job_ids: set[UUID] = set()
        for row in coverage_rows:
            if row.document_id is None:
                continue
            indexed_job_ids.add(row.job_id)
            hash_matches = bool(
                row.job_content_hash
                and row.version_content_hash
                and row.job_content_hash == row.version_content_hash
            )
            document_is_compatible = bool(
                row.knowledge_version == JOB_KNOWLEDGE_VERSION
                and row.current_embedding_signature == signature
                and row.document_chunk_count
                and not row.incompatible_chunk_count
                and hash_matches
            )
            if document_is_compatible:
                compatible_job_ids.add(row.job_id)
        compatible_jobs = len(compatible_job_ids)
        needs_update_jobs = max(0, int(jobs_total) - compatible_jobs)
        if not documents or not chunks:
            knowledge_status = "not_built"
        elif compatible_jobs == int(jobs_total) and jobs_total > 0:
            knowledge_status = "ready"
        elif len(indexed_job_ids) < int(jobs_total):
            knowledge_status = "partial"
        else:
            knowledge_status = "needs_update"
        active = await self.session.scalar(
            select(KnowledgeIndexRun)
            .where(KnowledgeIndexRun.status.in_(["PENDING", "RUNNING"]))
            .order_by(KnowledgeIndexRun.created_at)
            .limit(1)
        )
        latest = active or await self.session.scalar(
            select(KnowledgeIndexRun).order_by(KnowledgeIndexRun.created_at.desc()).limit(1)
        )
        return {
            "status": knowledge_status,
            "ready": knowledge_status == "ready" and active is None,
            "jobs_total": jobs_total,
            "document_count": documents,
            "indexed_jobs": indexed,
            "compatible_jobs": compatible_jobs,
            "needs_update_jobs": needs_update_jobs,
            "chunk_count": chunks,
            "embedded_chunk_count": embedded_chunks,
            "coverage_percent": round(compatible_jobs / max(1, int(jobs_total)) * 100, 1),
            "embedding_model": str(
                getattr(
                    self.embedding_provider,
                    "embedding_model",
                    getattr(self.embedding_provider, "model", self.settings.embedding_model),
                )
                or self.settings.embedding_model
            ),
            "embedding_dimensions": self.settings.embedding_dimensions,
            "updated_at": updated,
            "latest_run": latest,
        }

    async def get_run(self, run_id: UUID) -> KnowledgeIndexRun:
        run = await self.session.get(KnowledgeIndexRun, run_id, populate_existing=True)
        if run is None:
            raise KnowledgeIndexNotFoundError("知识库索引任务不存在")
        return run

    async def list_items(self, run_id: UUID) -> tuple[list[KnowledgeIndexRunItem], int]:
        await self.get_run(run_id)
        total = (
            await self.session.scalar(
                select(func.count(KnowledgeIndexRunItem.id)).where(
                    KnowledgeIndexRunItem.run_id == run_id
                )
            )
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(KnowledgeIndexRunItem)
                    .where(KnowledgeIndexRunItem.run_id == run_id)
                    .order_by(KnowledgeIndexRunItem.created_at, KnowledgeIndexRunItem.id)
                )
            ).all()
        )
        return items, int(total)

    async def create(self, payload: KnowledgeIndexRunCreate) -> KnowledgeIndexRun:
        job_ids = await self._select_job_ids(payload)
        run = KnowledgeIndexRun(
            mode=payload.mode,
            status="PENDING" if job_ids else "SUCCEEDED",
            stage="queued" if job_ids else "completed",
            progress=0 if job_ids else 100,
            total_jobs=len(job_ids),
            request_payload={
                "mode": payload.mode,
                "job_ids": [str(job_id) for job_id in job_ids],
                "force": payload.force,
            },
            completed_at=None if job_ids else _now(),
        )
        self.session.add(run)
        await self.session.flush()
        self.session.add_all(
            [KnowledgeIndexRunItem(run_id=run.id, job_id=job_id) for job_id in job_ids]
        )
        if job_ids and payload.auto_start and get_settings().independent_worker:
            await enqueue_work(
                self.session,
                "knowledge",
                run.id,
                delay_seconds=10 if payload.mode == "incremental" else 0,
            )
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def execute(
        self,
        run_id: UUID,
        embedding_provider: LLMProvider | None = None,
    ) -> KnowledgeIndexRun:
        provider = embedding_provider or self.embedding_provider
        if provider is None:
            raise KnowledgeIndexJobError("未配置 Embedding Provider，无法建立岗位知识库")
        run = await self.get_run(run_id)
        if run.status in KNOWLEDGE_INDEX_TERMINAL_STATUSES:
            return run

        run.status = "RUNNING"
        run.stage = "indexing"
        run.started_at = run.started_at or _now()
        run.error = None
        await self.session.commit()

        try:
            while True:
                run = await self.get_run(run_id)
                if run.status == "CANCELLED":
                    return run
                item = await self.session.scalar(
                    select(KnowledgeIndexRunItem)
                    .where(
                        KnowledgeIndexRunItem.run_id == run_id,
                        KnowledgeIndexRunItem.status == "PENDING",
                    )
                    .order_by(KnowledgeIndexRunItem.created_at, KnowledgeIndexRunItem.id)
                )
                if item is None:
                    run.current_job_id = None
                    run.progress = 100
                    run.stage = "completed" if run.failed_jobs == 0 else "completed_with_errors"
                    run.status = "SUCCEEDED" if run.failed_jobs == 0 else "FAILED"
                    run.completed_at = _now()
                    if run.failed_jobs:
                        run.error = f"{run.failed_jobs} 个岗位索引失败，可重试失败项。"
                    await self.session.commit()
                    return run

                item.status = "RUNNING"
                item.started_at = _now()
                run.current_job_id = item.job_id
                run.stage = "indexing_job"
                await self.session.commit()

                item_id = item.id
                try:
                    result = await self._index_job(
                        item.job_id,
                        provider,
                        force=bool(run.request_payload.get("force")),
                    )
                    item.status = "SKIPPED" if result.skipped else "SUCCEEDED"
                    item.chunk_count = result.chunk_count
                    item.reused_embedding_count = result.reused_embedding_count
                    item.finished_at = _now()
                    run.processed_jobs += 1
                    if result.skipped:
                        run.skipped_jobs += 1
                    else:
                        run.succeeded_jobs += 1
                    run.progress = round(run.processed_jobs / max(1, run.total_jobs) * 100)
                    run.result_payload = {
                        "last_job_id": str(item.job_id),
                        "last_chunk_count": result.chunk_count,
                        "last_reused_embedding_count": result.reused_embedding_count,
                    }
                    await self.session.commit()
                    if not result.skipped:
                        clear_knowledge_search_cache()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self.session.rollback()
                    run = await self.get_run(run_id)
                    item = await self.session.get(KnowledgeIndexRunItem, item_id)
                    if item is None:
                        continue
                    item.status = "FAILED"
                    item.error = str(exc)[:1000] or "岗位索引失败"
                    item.finished_at = _now()
                    run.processed_jobs += 1
                    run.failed_jobs += 1
                    run.progress = round(run.processed_jobs / max(1, run.total_jobs) * 100)
                    run.error = f"最近失败：{item.error}"
                    await self.session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.session.rollback()
            run = await self.get_run(run_id)
            if run.status not in KNOWLEDGE_INDEX_TERMINAL_STATUSES:
                active_item = await self.session.scalar(
                    select(KnowledgeIndexRunItem).where(
                        KnowledgeIndexRunItem.run_id == run_id,
                        KnowledgeIndexRunItem.status == "RUNNING",
                    )
                )
                if active_item is not None:
                    active_item.status = "FAILED"
                    active_item.error = str(exc)[:1000] or "岗位索引失败"
                    active_item.finished_at = _now()
                    run.processed_jobs += 1
                    run.failed_jobs += 1
                    run.progress = round(run.processed_jobs / max(1, run.total_jobs) * 100)
                run.status = "FAILED"
                run.stage = "failed"
                run.error = str(exc)[:1000] or "知识库索引失败"
                run.completed_at = _now()
                await self.session.commit()
            return run

    async def cancel(self, run_id: UUID) -> KnowledgeIndexRun:
        run = await self.get_run(run_id)
        if run.status in {"PENDING", "RUNNING"}:
            run.status = "CANCELLED"
            run.stage = "cancelled"
            run.error = "任务已由用户取消。"
            run.completed_at = _now()
            run.current_job_id = None
            await self.session.commit()
        return run

    async def retry(self, run_id: UUID) -> KnowledgeIndexRun:
        run = await self.get_run(run_id)
        if run.status not in {"FAILED", "CANCELLED"}:
            raise KnowledgeIndexActionError("只有失败或已取消的索引任务可以重试")
        await self.session.execute(
            update(KnowledgeIndexRunItem)
            .where(
                KnowledgeIndexRunItem.run_id == run_id,
                KnowledgeIndexRunItem.status.in_(["FAILED", "RUNNING", "PENDING"]),
            )
            .values(status="PENDING", error=None, started_at=None, finished_at=None)
        )
        run.status = "PENDING"
        run.stage = "queued"
        run.error = None
        run.completed_at = None
        run.current_job_id = None
        run.processed_jobs = run.succeeded_jobs + run.skipped_jobs
        run.failed_jobs = 0
        run.progress = round(run.processed_jobs / max(1, run.total_jobs) * 100)
        if get_settings().independent_worker:
            await enqueue_work(self.session, "knowledge", run.id, retry=True)
        await self.session.commit()
        return run

    async def _select_job_ids(self, payload: KnowledgeIndexRunCreate) -> list[UUID]:
        if payload.job_ids:
            existing = set(
                (
                    await self.session.scalars(select(Job.id).where(Job.id.in_(payload.job_ids)))
                ).all()
            )
            missing = [job_id for job_id in payload.job_ids if job_id not in existing]
            if missing:
                raise KnowledgeIndexActionError(
                    f"岗位不存在：{', '.join(str(item) for item in missing)}"
                )
            return list(dict.fromkeys(payload.job_ids))

        jobs = list(
            (await self.session.scalars(select(Job).order_by(Job.created_at, Job.id))).all()
        )
        if payload.mode == "backfill":
            return [job.id for job in jobs]

        documents = list(
            (
                await self.session.scalars(
                    select(JobKnowledgeDocument).options(
                        selectinload(JobKnowledgeDocument.job_version),
                        selectinload(JobKnowledgeDocument.chunks),
                    )
                )
            ).all()
        )
        by_job: dict[UUID, list[JobKnowledgeDocument]] = {}
        for document in documents:
            by_job.setdefault(document.job_id, []).append(document)
        provider = self.embedding_provider
        signature = _embedding_signature(provider, self.settings) if provider is not None else ""
        return [
            job.id
            for job in jobs
            if self._job_needs_index(
                job,
                by_job.get(job.id, []),
                signature,
                self.settings.embedding_dimensions,
            )
        ]

    @staticmethod
    def _job_needs_index(
        job: Job,
        documents: list[JobKnowledgeDocument],
        embedding_signature: str,
        embedding_dimensions: int,
    ) -> bool:
        current = next((document for document in documents if document.active), None)
        if current is None or current.job_version is None:
            return True
        if current.job_version.content_hash != _job_content_hash(job):
            return True
        if current.knowledge_version != JOB_KNOWLEDGE_VERSION:
            return True
        if embedding_signature and current.current_embedding_signature != embedding_signature:
            return True
        if not current.chunks:
            return True
        chunk_keys = [
            (chunk.section_type, chunk.content_hash)
            for chunk in current.chunks
        ]
        if len(chunk_keys) != len(set(chunk_keys)):
            return True
        return any(
            chunk.embedding is None
            or chunk.embedding_dimensions != embedding_dimensions
            or (
                embedding_signature
                and chunk.embedding_signature != embedding_signature
            )
            for chunk in current.chunks
        )

    async def _index_job(
        self,
        job_id: UUID,
        provider: LLMProvider,
        *,
        force: bool,
    ) -> IndexedJobResult:
        job = await self.session.scalar(
            select(Job)
            .options(
                selectinload(Job.skills),
                selectinload(Job.company),
                selectinload(Job.requirements),
            )
            .where(Job.id == job_id)
        )
        if job is None:
            raise KnowledgeIndexJobError("岗位在索引过程中不存在")
        signature = _embedding_signature(provider, self.settings)
        current_hash = _job_content_hash(job)
        documents = list(
            (
                await self.session.scalars(
                    select(JobKnowledgeDocument)
                    .options(
                        selectinload(JobKnowledgeDocument.job_version),
                        selectinload(JobKnowledgeDocument.chunks),
                    )
                    .where(JobKnowledgeDocument.job_id == job.id)
                )
            ).all()
        )
        current_document = next((document for document in documents if document.active), None)
        if (
            not force
            and current_document is not None
            and current_document.job_version is not None
            and current_document.job_version.content_hash == current_hash
            and current_document.knowledge_version == JOB_KNOWLEDGE_VERSION
            and current_document.current_embedding_signature == signature
            and current_document.chunks
        ):
            return IndexedJobResult(
                skipped=True,
                chunk_count=len(current_document.chunks),
                reused_embedding_count=len(current_document.chunks),
            )

        version = await self.session.scalar(
            select(JobVersion).where(
                JobVersion.job_id == job.id,
                JobVersion.content_hash == current_hash,
            )
        )
        if version is None:
            latest = await self.session.scalar(
                select(func.max(JobVersion.version_number)).where(JobVersion.job_id == job.id)
            )
            version = JobVersion(
                job_id=job.id,
                version_number=int(latest or 0) + 1,
                raw_title=job.title,
                raw_description=job.description,
                raw_payload=job.raw_data or {},
                content_hash=current_hash,
                source_platform=job.platform,
                source_url=job.source_url,
                collected_at=job.updated_at or _now(),
                published_at=job.publish_time,
                parser_version=JOB_KNOWLEDGE_PARSER_VERSION,
                is_current=True,
            )
            self.session.add(version)
            await self.session.flush()
        else:
            version.raw_title = job.title
            version.raw_description = job.description
            version.raw_payload = job.raw_data or {}
            version.source_platform = job.platform
            version.source_url = job.source_url
            version.published_at = job.publish_time
            version.parser_version = JOB_KNOWLEDGE_PARSER_VERSION
            version.is_current = True

        await self.session.execute(
            update(JobVersion)
            .where(JobVersion.job_id == job.id, JobVersion.id != version.id)
            .values(is_current=False)
        )

        structured = _structured_job(job)
        if current_document is None or current_document.job_version_id != version.id:
            await self.session.execute(
                update(JobKnowledgeDocument)
                .where(JobKnowledgeDocument.job_id == job.id)
                .values(active=False)
            )
            current_document = JobKnowledgeDocument(
                job_id=job.id,
                job_version_id=version.id,
                role_family=str(structured.get("role_category") or "").strip(),
                normalized_title=job.title,
                normalized_city=job.location or str(structured.get("location") or "").strip(),
                normalized_education=(
                    str(structured.get("education_requirement") or "").strip()
                    or job.education_requirement
                    or ""
                ),
                normalized_experience=_normalized_experience(job, structured),
                salary_min=job.salary_min,
                salary_max=job.salary_max,
                salary_unit=_salary_unit(job),
                employment_type=job.job_type or str(structured.get("job_type") or "").strip(),
                current_embedding_signature=signature,
                knowledge_version=JOB_KNOWLEDGE_VERSION,
                active=True,
            )
            self.session.add(current_document)
            await self.session.flush()
        else:
            current_document.role_family = str(structured.get("role_category") or "").strip()
            current_document.normalized_title = job.title
            current_document.normalized_city = (
                job.location or str(structured.get("location") or "").strip()
            )
            current_document.normalized_education = (
                str(structured.get("education_requirement") or "").strip()
                or job.education_requirement
                or ""
            )
            current_document.normalized_experience = _normalized_experience(job, structured)
            current_document.salary_min = job.salary_min
            current_document.salary_max = job.salary_max
            current_document.salary_unit = _salary_unit(job)
            current_document.employment_type = (
                job.job_type or str(structured.get("job_type") or "").strip()
            )
            current_document.current_embedding_signature = signature
            current_document.knowledge_version = JOB_KNOWLEDGE_VERSION
            current_document.active = True

        # The database uniqueness boundary is section + content hash. Some
        # imported/legacy normalized payloads can produce the same section
        # twice, so normalize drafts before embedding and inserting them.
        drafts = []
        seen_draft_keys: set[tuple[str, str]] = set()
        for draft in build_job_knowledge_chunks(
            job,
            token_counter=token_counter_for_provider(provider),
        ):
            draft_key = (draft.section_type, draft.content_hash)
            if draft_key in seen_draft_keys:
                continue
            seen_draft_keys.add(draft_key)
            drafts.append(draft)
        draft_keys = [(draft.section_type, draft.content_hash) for draft in drafts]
        hashes = [content_hash for _, content_hash in draft_keys]
        reusable_chunks = (
            list(
                (
                    await self.session.scalars(
                        select(JobKnowledgeChunk).where(
                            JobKnowledgeChunk.content_hash.in_(hashes),
                            JobKnowledgeChunk.embedding_signature == signature,
                        )
                    )
                ).all()
            )
            if hashes
            else []
        )
        reusable_by_key = {
            (chunk.section_type, chunk.content_hash): chunk
            for chunk in reusable_chunks
            if len(chunk.embedding or []) == self.settings.embedding_dimensions
        }

        missing = [
            draft
            for draft in drafts
            if (draft.section_type, draft.content_hash) not in reusable_by_key
        ]
        generated_vectors = await embed_texts(
            provider,
            [draft.content for draft in missing],
            model=self.settings.embedding_model,
        )
        generated_by_key = {
            (draft.section_type, draft.content_hash): vector
            for draft, vector in zip(missing, generated_vectors, strict=True)
        }

        embeddings: list[tuple[Any, list[float]]] = []
        reused = 0
        for draft in drafts:
            cached = reusable_by_key.get((draft.section_type, draft.content_hash))
            if cached is not None and cached.embedding is not None:
                embedding = list(cached.embedding)
                reused += 1
            else:
                embedding = list(generated_by_key[(draft.section_type, draft.content_hash)])
            if len(embedding) != self.settings.embedding_dimensions:
                raise KnowledgeIndexJobError(
                    "Embedding 维度不匹配："
                    f"期望 {self.settings.embedding_dimensions}，实际 {len(embedding)}"
                )
            embeddings.append((draft, embedding))

        await self.session.execute(
            delete(JobKnowledgeChunk).where(JobKnowledgeChunk.document_id == current_document.id)
        )
        chunk_rows: list[JobKnowledgeChunk] = []
        company_name = str((job.raw_data or {}).get("company_name") or "").strip()
        if not company_name and job.company is not None:
            company_name = job.company.name
        for draft, embedding in embeddings:
            chunk_id = uuid4()
            chunk_rows.append(
                JobKnowledgeChunk(
                    id=chunk_id,
                    document_id=current_document.id,
                    job_id=job.id,
                    section_type=draft.section_type,
                    content=draft.content,
                    content_hash=draft.content_hash,
                    token_count=draft.token_count,
                    embedding=embedding,
                    embedding_provider=str(
                        getattr(
                            provider,
                            "embedding_provider_name",
                            getattr(provider, "provider_name", "unknown"),
                        )
                    ),
                    embedding_model=str(
                        getattr(provider, "embedding_model", getattr(provider, "model", "unknown"))
                    ),
                    embedding_dimensions=len(embedding),
                    embedding_signature=signature,
                    chunk_metadata={
                        **draft.metadata,
                        "document_id": str(current_document.id),
                        "chunk_id": str(chunk_id),
                        "parent_id": str(current_document.id),
                        "filename": f"{job.platform}-{job.title}",
                        "title": job.title,
                        "section": draft.section_type,
                        "page": None,
                        "document_type": "job_description",
                        "author": company_name,
                        "created_at": (
                            current_document.created_at.isoformat()
                            if current_document.created_at
                            else None
                        ),
                        "updated_at": (
                            current_document.updated_at.isoformat()
                            if current_document.updated_at
                            else None
                        ),
                        "tags": [skill.skill_name for skill in job.skills[:20]],
                        "knowledge_version": JOB_KNOWLEDGE_VERSION,
                        "source_job_id": str(job.id),
                    },
                )
            )
        self.session.add_all(chunk_rows)
        await self._refresh_skill_facts(job)
        return IndexedJobResult(
            skipped=False,
            chunk_count=len(embeddings),
            reused_embedding_count=reused,
        )

    async def _refresh_skill_facts(self, job: Job) -> None:
        await self.session.execute(delete(JobSkillFact).where(JobSkillFact.job_id == job.id))
        sources: list[tuple[str, str, float]] = []
        for skill in job.skills:
            sources.append((skill.skill_name, skill.skill_type, skill.confidence))
        structured = _structured_job(job)
        sources.extend(
            (str(name), "required", 0.7)
            for name in structured.get("required_skills") or []
            if str(name).strip()
        )
        sources.extend(
            (str(name), "preferred", 0.6)
            for name in structured.get("preferred_skills") or []
            if str(name).strip()
        )

        unique: dict[str, tuple[str, str, float]] = {}
        priority = {"inferred": 1, "preferred": 2, "required": 3}
        for raw_name, raw_type, confidence in sources:
            canonical = canonicalize_skill(raw_name)
            normalized = normalize_skill_name(canonical)
            if not normalized:
                continue
            requirement_type = raw_type if raw_type in {"required", "preferred"} else "inferred"
            existing = unique.get(normalized)
            if existing is None or priority[requirement_type] > priority[existing[1]]:
                unique[normalized] = (
                    canonical,
                    requirement_type,
                    max(0.0, min(1.0, confidence)),
                )

        for normalized, (canonical, requirement_type, confidence) in unique.items():
            skill = await self.session.scalar(
                select(SkillTaxonomy).where(SkillTaxonomy.canonical_name == canonical)
            )
            if skill is None:
                alias_skill = await self.session.scalar(
                    select(SkillAlias).where(SkillAlias.normalized_alias == normalized)
                )
                skill = (
                    await self.session.get(SkillTaxonomy, alias_skill.skill_id)
                    if alias_skill
                    else None
                )
            if skill is None:
                skill = SkillTaxonomy(
                    canonical_name=canonical,
                    category=skill_category(canonical),
                    description="",
                    active=True,
                )
                self.session.add(skill)
                await self.session.flush()
            alias = await self.session.scalar(
                select(SkillAlias).where(SkillAlias.normalized_alias == normalized)
            )
            if alias is None:
                self.session.add(
                    SkillAlias(
                        skill_id=skill.id,
                        alias=canonical,
                        normalized_alias=normalized,
                    )
                )
            evidence = _skill_evidence(job.description, canonical)
            self.session.add(
                JobSkillFact(
                    job_id=job.id,
                    skill_id=skill.id,
                    requirement_type=requirement_type,
                    evidence=evidence,
                    confidence=confidence,
                    parser_version=JOB_KNOWLEDGE_PARSER_VERSION,
                )
            )


def _skill_evidence(description: str, skill_name: str) -> str:
    aliases = {skill_name.casefold(), normalize_skill_name(skill_name)}
    for line in (description or "").splitlines():
        lowered = normalize_skill_name(line)
        if any(alias and alias in lowered for alias in aliases):
            return line.strip()[:500]
    # A derived skill is not evidence by itself. Keep the fact but leave its
    # evidence empty so downstream agents can distinguish source text from an
    # inference and avoid presenting invented quotations.
    return ""


_active_knowledge_tasks: dict[UUID, asyncio.Task[None]] = {}


async def execute_knowledge_index(run_id: UUID) -> None:
    async with SessionLocal() as session:
        try:
            from app.services.llm_settings import LLMSettingsService

            provider = await LLMSettingsService(session).get_runtime_embedding_provider()
            await KnowledgeIndexService(session, provider).execute(run_id, provider)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            service = KnowledgeIndexService(session)
            try:
                run = await service.get_run(run_id)
                run.status = "FAILED"
                run.stage = "failed"
                run.error = str(exc)[:1000] or "知识库索引失败"
                run.completed_at = _now()
                await session.commit()
            except KnowledgeIndexNotFoundError:
                return


def schedule_knowledge_index(run_id: UUID) -> None:
    if get_settings().independent_worker:
        return
    existing = _active_knowledge_tasks.get(run_id)
    if existing is not None and not existing.done():
        return
    task = asyncio.create_task(execute_knowledge_index(run_id))
    _active_knowledge_tasks[run_id] = task
    task.add_done_callback(lambda _: _active_knowledge_tasks.pop(run_id, None))


async def enqueue_incremental_knowledge_index(
    session: AsyncSession,
    job_ids: list[UUID],
    *,
    force: bool = False,
) -> UUID | None:
    """Persist and start one incremental run for newly written job records.

    The run is created with the caller's transaction/session so a successful
    job write always leaves a durable indexing checkpoint. Runtime execution
    uses its own session and is only scheduled for the production PostgreSQL
    process; this keeps SQLite unit-test sessions isolated from the developer
    database while preserving the same persisted behavior.
    """
    unique_job_ids = list(dict.fromkeys(job_ids))
    if not unique_job_ids:
        return None
    bind = getattr(session.sync_session, "bind", None)
    if bind is not None and bind.dialect.name == "postgresql":
        # A short durable debounce turns rapid imports into one run. The queue's
        # available_at gives other API workers time to join before execution.
        from sqlalchemy import text

        await session.execute(text("SELECT pg_advisory_xact_lock(4200917)"))
        pending = await session.scalar(
            select(KnowledgeIndexRun)
            .join(BackgroundWork, BackgroundWork.run_id == KnowledgeIndexRun.id)
            .where(
                BackgroundWork.kind == "knowledge",
                BackgroundWork.status == "PENDING",
                KnowledgeIndexRun.mode == "incremental",
                KnowledgeIndexRun.status == "PENDING",
                KnowledgeIndexRun.created_at >= _now() - timedelta(seconds=10),
            )
            .order_by(KnowledgeIndexRun.created_at.desc())
            .with_for_update()
        )
        if pending is not None:
            existing = set(
                await session.scalars(
                    select(KnowledgeIndexRunItem.job_id).where(
                        KnowledgeIndexRunItem.run_id == pending.id
                    )
                )
            )
            added = [job_id for job_id in unique_job_ids if job_id not in existing]
            if added:
                session.add_all(
                    [KnowledgeIndexRunItem(run_id=pending.id, job_id=job_id) for job_id in added]
                )
                request = dict(pending.request_payload)
                request["job_ids"] = list(
                    dict.fromkeys([*request.get("job_ids", []), *(str(value) for value in added)])
                )
                pending.request_payload = request
                pending.total_jobs += len(added)
                work = await session.scalar(
                    select(BackgroundWork).where(
                        BackgroundWork.kind == "knowledge",
                        BackgroundWork.run_id == pending.id,
                    )
                )
                if work is not None:
                    work.available_at = min(
                        _now() + timedelta(seconds=5), pending.created_at + timedelta(seconds=15)
                    )
            if force:
                pending.request_payload = {
                    **dict(pending.request_payload),
                    "force": True,
                }
            if added or force:
                await session.commit()
            return pending.id
    run = await KnowledgeIndexService(session).create(
        KnowledgeIndexRunCreate(
            mode="incremental",
            job_ids=unique_job_ids,
            force=force,
            auto_start=True,
        )
    )
    if bind is not None and bind.dialect.name == "postgresql":
        schedule_knowledge_index(run.id)
    return run.id


def stop_knowledge_index(run_id: UUID) -> None:
    task = _active_knowledge_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()


async def recover_interrupted_knowledge_indexes() -> list[UUID]:
    if get_settings().independent_worker:
        return []
    async with SessionLocal() as session:
        run_ids = list(
            (
                await session.scalars(
                    select(KnowledgeIndexRun.id).where(
                        KnowledgeIndexRun.status.in_(["PENDING", "RUNNING"])
                    )
                )
            ).all()
        )
        if run_ids:
            await session.execute(
                update(KnowledgeIndexRun)
                .where(KnowledgeIndexRun.id.in_(run_ids))
                .values(
                    status="PENDING",
                    stage="recovering",
                    current_job_id=None,
                    error="API 服务重启，任务将从已持久化的岗位检查点恢复。",
                )
            )
            await session.execute(
                update(KnowledgeIndexRunItem)
                .where(
                    KnowledgeIndexRunItem.run_id.in_(run_ids),
                    KnowledgeIndexRunItem.status == "RUNNING",
                )
                .values(status="PENDING", started_at=None, error=None)
            )
            await session.commit()
        return run_ids


async def run_knowledge_consistency_check() -> dict[str, Any]:
    """Run a read-only startup check without scheduling or computing embeddings."""

    embedding_provider: LLMProvider | None = None
    try:
        from app.services.llm_settings import LLMSettingsService

        async with SessionLocal() as session:
            try:
                embedding_provider = await LLMSettingsService(
                    session
                ).get_runtime_embedding_provider()
            except Exception:
                # A missing optional provider must not prevent the API from
                # starting. The health result will still report the counts.
                embedding_provider = None
            return await KnowledgeIndexService(session, embedding_provider).health()
    except Exception:
        # Startup diagnostics are best-effort and must never create a recovery
        # task or make the application unavailable.
        return {"status": "not_built", "ready": False, "check_failed": True}


async def shutdown_knowledge_index_tasks() -> None:
    tasks = [task for task in _active_knowledge_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_knowledge_tasks.clear()
