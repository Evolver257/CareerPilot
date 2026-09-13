from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.llm.provider import LLMProvider
from app.models.entities import AgentMemory, MemoryEmbeddingRun, User
from app.services.work_queue import enqueue_work

MEMORY_EMBEDDING_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}
_active_tasks: dict[UUID, asyncio.Task[None]] = {}


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryEmbeddingError(ValueError):
    pass


class MemoryEmbeddingService:
    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: LLMProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider
        self.settings = settings or get_settings()

    def _embedding_identity(self, provider: LLMProvider | None = None) -> tuple[str, str]:
        source = provider or self.embedding_provider
        model = str(
            getattr(source, "embedding_model", "") or self.settings.embedding_model
        )
        signature = str(getattr(source, "embedding_signature", "") or "")
        if not signature:
            signature = (
                f"{getattr(source, 'provider_name', 'unknown')}"
                f":{model}:{self.settings.embedding_dimensions}"
            )
        return model, signature

    async def default_user_id(self) -> UUID:
        user = await self.session.scalar(
            select(User).where(User.email == self.settings.default_user_email)
        )
        if user is None:
            user = User(
                email=self.settings.default_user_email,
                name=self.settings.default_user_name,
            )
            self.session.add(user)
            await self.session.flush()
        return user.id

    async def _target_ids(self, user_id: UUID, mode: str) -> list[UUID]:
        query = select(AgentMemory.id).where(
            AgentMemory.user_id == user_id,
            AgentMemory.deleted_at.is_(None),
        )
        if mode == "incremental":
            model, signature = self._embedding_identity()
            query = query.where(
                or_(
                    AgentMemory.embedding.is_(None),
                    AgentMemory.embedding == None,  # noqa: E711 - JSON null on SQLite
                    AgentMemory.embedding_signature.is_(None),
                    AgentMemory.embedding_model.is_(None),
                    AgentMemory.embedding_signature != signature,
                    AgentMemory.embedding_model != model,
                )
            )
        return list((await self.session.scalars(query.order_by(AgentMemory.created_at))).all())

    async def create(self, *, mode: str = "incremental") -> MemoryEmbeddingRun:
        if mode not in {"full", "incremental"}:
            raise MemoryEmbeddingError("不支持的记忆向量回填模式")
        user_id = await self.default_user_id()
        memory_ids = await self._target_ids(user_id, mode)
        run = MemoryEmbeddingRun(
            user_id=user_id,
            mode=mode,
            status="PENDING" if memory_ids else "SUCCEEDED",
            progress=0 if memory_ids else 100,
            total=len(memory_ids),
            request_payload={"mode": mode, "memory_ids": [str(item) for item in memory_ids]},
            completed_at=None if memory_ids else _now(),
        )
        self.session.add(run)
        await self.session.flush()
        if memory_ids and self.settings.independent_worker:
            await enqueue_work(self.session, "memory_embedding", run.id)
        await self.session.commit()
        await self.session.refresh(run)
        if memory_ids and not self.settings.independent_worker:
            schedule_memory_embedding(run.id)
        return run

    async def create_maintenance(self) -> MemoryEmbeddingRun:
        """Create an idempotent, durable hygiene scan for the current user."""

        user_id = await self.default_user_id()
        existing = await self.session.scalar(
            select(MemoryEmbeddingRun)
            .where(
                MemoryEmbeddingRun.user_id == user_id,
                MemoryEmbeddingRun.mode == "maintenance",
                MemoryEmbeddingRun.status.in_(["PENDING", "RUNNING"]),
            )
            .order_by(MemoryEmbeddingRun.created_at.desc())
        )
        if existing is not None:
            return existing
        memory_ids = list(
            (
                await self.session.scalars(
                    select(AgentMemory.id)
                    .where(
                        AgentMemory.user_id == user_id,
                        AgentMemory.deleted_at.is_(None),
                        AgentMemory.status == "ACTIVE",
                    )
                    .order_by(AgentMemory.created_at)
                )
            ).all()
        )
        run = MemoryEmbeddingRun(
            user_id=user_id,
            mode="maintenance",
            status="PENDING" if memory_ids else "SUCCEEDED",
            progress=0 if memory_ids else 100,
            total=len(memory_ids),
            request_payload={
                "mode": "maintenance",
                "memory_ids": [str(item) for item in memory_ids],
            },
            completed_at=None if memory_ids else _now(),
        )
        self.session.add(run)
        await self.session.flush()
        if memory_ids and self.settings.independent_worker:
            await enqueue_work(self.session, "memory_embedding", run.id)
        await self.session.commit()
        await self.session.refresh(run)
        if memory_ids and not self.settings.independent_worker:
            schedule_memory_embedding(run.id)
        return run

    async def get(self, run_id: UUID) -> MemoryEmbeddingRun:
        user_id = await self.default_user_id()
        run = await self.session.scalar(
            select(MemoryEmbeddingRun).where(
                MemoryEmbeddingRun.id == run_id,
                MemoryEmbeddingRun.user_id == user_id,
            )
        )
        if run is None:
            raise MemoryEmbeddingError("记忆 Embedding 任务不存在")
        return run

    async def resolve_maintenance_action(
        self,
        run_id: UUID,
        *,
        action: str,
        source_memory_id: UUID,
        target_memory_id: UUID,
    ) -> MemoryEmbeddingRun:
        """Apply one user-confirmed duplicate merge or conflict resolution."""

        if action not in {"merge_duplicate", "supersede_conflict"}:
            raise MemoryEmbeddingError("不支持的记忆维护操作")
        if source_memory_id == target_memory_id:
            raise MemoryEmbeddingError("源记忆和保留记忆不能相同")
        run = await self.get(run_id)
        if run.mode != "maintenance":
            raise MemoryEmbeddingError("只有维护任务支持治理操作")
        memories = list(
            (
                await self.session.scalars(
                    select(AgentMemory).where(
                        AgentMemory.id.in_([source_memory_id, target_memory_id]),
                        AgentMemory.user_id == run.user_id,
                        AgentMemory.status == "ACTIVE",
                        AgentMemory.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        by_id = {item.id: item for item in memories}
        source = by_id.get(source_memory_id)
        target = by_id.get(target_memory_id)
        if source is None or target is None:
            raise MemoryEmbeddingError("待处理的记忆不存在、已删除或已处理")
        if action == "merge_duplicate":
            if (
                source.normalized_content != target.normalized_content
                or source.memory_type != target.memory_type
                or source.scope != target.scope
            ):
                raise MemoryEmbeddingError("只有同类型、同作用域的完全重复记忆才能合并")
            target.pinned = target.pinned or source.pinned
            target.use_count = int(target.use_count or 0) + int(source.use_count or 0)
            provenance = dict(target.provenance or {})
            merged = list(provenance.get("merged_memory_ids", []))
            if str(source.id) not in merged:
                merged.append(str(source.id))
            provenance["merged_memory_ids"] = merged[-100:]
            target.provenance = provenance
            source.deleted_from_status = source.status
            source.deleted_at = _now()
            source.status = "DELETED"
        else:
            if (
                source.memory_key != target.memory_key
                or source.memory_type != target.memory_type
                or source.scope != target.scope
            ):
                raise MemoryEmbeddingError("冲突解决要求同一记忆属性和作用域")
            provenance = dict(source.provenance or {})
            provenance["superseded_by"] = str(target.id)
            source.provenance = provenance
            source.status = "SUPERSEDED"
            source.last_verified_at = _now()
            target.last_verified_at = _now()
        actions = list((run.result_payload or {}).get("resolved_actions", []))
        actions.append(
            {
                "action": action,
                "source_memory_id": str(source.id),
                "target_memory_id": str(target.id),
                "resolved_at": _now().isoformat(),
            }
        )
        run.result_payload = {**(run.result_payload or {}), "resolved_actions": actions[-100:]}
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def list_runs(self, *, limit: int = 20, offset: int = 0) -> list[MemoryEmbeddingRun]:
        user_id = await self.default_user_id()
        return list(
            (
                await self.session.scalars(
                    select(MemoryEmbeddingRun)
                    .where(MemoryEmbeddingRun.user_id == user_id)
                    .order_by(MemoryEmbeddingRun.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )

    async def health(self) -> dict[str, object]:
        user_id = await self.default_user_id()
        total = int(
            await self.session.scalar(
                select(func.count(AgentMemory.id)).where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.deleted_at.is_(None),
                )
            )
            or 0
        )
        model, signature = self._embedding_identity()
        embedded_clauses = [
            AgentMemory.user_id == user_id,
            AgentMemory.deleted_at.is_(None),
            AgentMemory.embedding_signature.is_not(None),
            AgentMemory.embedding_model == model,
        ]
        if signature:
            embedded_clauses.append(AgentMemory.embedding_signature == signature)
        embedded = int(
            await self.session.scalar(
                select(func.count(AgentMemory.id)).where(*embedded_clauses)
            )
            or 0
        )
        latest = await self.session.scalar(
            select(MemoryEmbeddingRun)
            .where(MemoryEmbeddingRun.user_id == user_id)
            .order_by(MemoryEmbeddingRun.created_at.desc())
            .limit(1)
        )
        return {
            "embedding_model": model,
            "embedding_dimensions": self.settings.embedding_dimensions,
            "provider_available": self.embedding_provider is not None,
            "status": (
                "ready"
                if self.embedding_provider is not None and embedded == total
                else "partial"
            ),
            "total": total,
            "embedded": embedded,
            "pending": max(0, total - embedded),
            "failed": int(latest.failed if latest else 0),
            "latest_run": latest,
        }

    async def cancel(self, run_id: UUID) -> MemoryEmbeddingRun:
        run = await self.get(run_id)
        if run.status in {"PENDING", "RUNNING"}:
            run.status = "CANCELLED"
            run.error = "任务已由用户取消"
            run.completed_at = _now()
            await self.session.commit()
        return run

    async def retry(self, run_id: UUID) -> MemoryEmbeddingRun:
        run = await self.get(run_id)
        if run.status not in {"FAILED", "CANCELLED"}:
            raise MemoryEmbeddingError("只有失败或已取消的回填任务可以重试")
        return await (
            self.create_maintenance()
            if run.mode == "maintenance"
            else self.create(mode="incremental")
        )

    async def execute(
        self,
        run_id: UUID,
        embedding_provider: LLMProvider | None = None,
    ) -> MemoryEmbeddingRun:
        run = await self.get(run_id)
        if run.status in MEMORY_EMBEDDING_TERMINAL_STATUSES:
            return run
        if run.mode == "maintenance":
            return await self._execute_maintenance(
                run, embedding_provider or self.embedding_provider
            )
        provider = embedding_provider or self.embedding_provider
        if provider is None:
            raise MemoryEmbeddingError("未配置 Embedding Provider，无法回填记忆向量")
        memory_ids = [UUID(value) for value in run.request_payload.get("memory_ids", [])]
        run.status = "RUNNING"
        run.started_at = run.started_at or _now()
        run.error = None
        await self.session.commit()
        failures: list[dict[str, str]] = list(run.result_payload.get("failures", []))
        processed = int(run.processed or 0)
        succeeded = int(run.succeeded or 0)
        failed = int(run.failed or 0)
        model, signature = self._embedding_identity(provider)
        try:
            for memory_id in memory_ids[processed:]:
                current = await self.get(run_id)
                if current.status == "CANCELLED":
                    return current
                memory = await self.session.scalar(
                    select(AgentMemory).where(
                        AgentMemory.id == memory_id,
                        AgentMemory.user_id == run.user_id,
                        AgentMemory.deleted_at.is_(None),
                    )
                )
                run.current_memory_id = memory_id
                if memory is None:
                    failed += 1
                    failures.append({"memory_id": str(memory_id), "error": "记忆不存在或已删除"})
                else:
                    try:
                        vector = list(
                            await asyncio.wait_for(
                                provider.embed(
                                    memory.content, model=self.settings.embedding_model
                                ),
                                timeout=30,
                            )
                        )
                        if len(vector) != self.settings.embedding_dimensions:
                            raise MemoryEmbeddingError(
                                "向量维度不匹配："
                                f"{len(vector)} != {self.settings.embedding_dimensions}"
                            )
                        memory.embedding = vector
                        memory.embedding_model = model
                        memory.embedding_signature = signature
                        succeeded += 1
                    except Exception as exc:
                        failed += 1
                        failures.append({"memory_id": str(memory_id), "error": str(exc)[:240]})
                processed += 1
                run.processed = processed
                run.succeeded = succeeded
                run.failed = failed
                run.progress = round(processed / max(1, run.total) * 100)
                run.result_payload = {
                    "failures": failures[-100:],
                    "embedding_model": model,
                    "embedding_signature": signature,
                }
                await self.session.commit()
            run.status = "FAILED" if failed else "SUCCEEDED"
            run.progress = 100
            run.completed_at = _now()
            run.current_memory_id = None
            if failed:
                run.error = f"{failed} 条记忆向量化失败，可重试"
            await self.session.commit()
            await self.session.refresh(run)
            return run
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.session.rollback()
            failed_run = await self.get(run_id)
            failed_run.status = "FAILED"
            failed_run.error = str(exc)[:500]
            failed_run.completed_at = _now()
            await self.session.commit()
            return failed_run

    async def _execute_maintenance(
        self,
        run: MemoryEmbeddingRun,
        embedding_provider: LLMProvider | None = None,
    ) -> MemoryEmbeddingRun:
        """Run safe memory hygiene actions and produce reviewable governance findings.

        Expiration and vector repair are safe, deterministic operations. Possible
        merges or conflicts are intentionally only reported in the result payload;
        changing user meaning requires an explicit user action.
        """

        memory_ids = [UUID(value) for value in run.request_payload.get("memory_ids", [])]
        run.status = "RUNNING"
        run.started_at = run.started_at or _now()
        run.error = None
        await self.session.commit()
        processed = int(run.processed or 0)
        succeeded = int(run.succeeded or 0)
        failed = int(run.failed or 0)
        expired = 0
        reembedded = 0
        failures: list[dict[str, str]] = list(run.result_payload.get("failures", []))
        model, signature = self._embedding_identity(embedding_provider)
        try:
            for memory_id in memory_ids[processed:]:
                current = await self.get(run.id)
                if current.status == "CANCELLED":
                    return current
                memory = await self.session.scalar(
                    select(AgentMemory).where(
                        AgentMemory.id == memory_id,
                        AgentMemory.user_id == run.user_id,
                        AgentMemory.deleted_at.is_(None),
                    )
                )
                run.current_memory_id = memory_id
                if memory is None:
                    failed += 1
                    failures.append({"memory_id": str(memory_id), "error": "记忆不存在或已删除"})
                else:
                    if (
                        memory.status == "ACTIVE"
                        and not memory.pinned
                        and memory.valid_until is not None
                        and memory.valid_until < _now()
                    ):
                        memory.status = "EXPIRED"
                        expired += 1
                    needs_embedding = (
                        embedding_provider is not None
                        and (
                            memory.embedding is None
                            or memory.embedding_model != model
                            or memory.embedding_signature != signature
                        )
                    )
                    if needs_embedding:
                        try:
                            vector = list(
                                await asyncio.wait_for(
                                    embedding_provider.embed(
                                        memory.content,
                                        model=self.settings.embedding_model,
                                    ),
                                    timeout=30,
                                )
                            )
                            if len(vector) != self.settings.embedding_dimensions:
                                raise MemoryEmbeddingError(
                                    "向量维度不匹配："
                                    f"{len(vector)} != {self.settings.embedding_dimensions}"
                                )
                            memory.embedding = vector
                            memory.embedding_model = model
                            memory.embedding_signature = signature
                            reembedded += 1
                        except Exception as exc:
                            failed += 1
                            failures.append(
                                {
                                    "memory_id": str(memory_id),
                                    "error": f"embedding_repair_failed: {str(exc)[:200]}",
                                }
                            )
                    succeeded += 1
                processed += 1
                run.processed = processed
                run.succeeded = succeeded
                run.failed = failed
                run.progress = round(processed / max(1, run.total) * 100)
                run.result_payload = {
                    "expired": expired,
                    "reembedded": reembedded,
                    "failures": failures[-100:],
                }
                await self.session.commit()

            stale = int(
                await self.session.scalar(
                    select(func.count(AgentMemory.id)).where(
                        AgentMemory.user_id == run.user_id,
                        AgentMemory.deleted_at.is_(None),
                        or_(
                            AgentMemory.embedding.is_(None),
                            AgentMemory.embedding_signature != signature,
                            AgentMemory.embedding_model != model,
                        ),
                    )
                )
                or 0
            )
            active_rows = list(
                (
                    await self.session.execute(
                        select(
                            AgentMemory.id,
                            AgentMemory.memory_key,
                            AgentMemory.memory_type,
                            AgentMemory.scope,
                            AgentMemory.normalized_content,
                        ).where(
                            AgentMemory.user_id == run.user_id,
                            AgentMemory.status == "ACTIVE",
                            AgentMemory.deleted_at.is_(None),
                        )
                    )
                ).all()
            )
            conflicts: dict[str, list[dict[str, str]]] = {}
            duplicates: dict[str, list[str]] = {}
            for memory_id, memory_key, memory_type, scope, normalized_content in active_rows:
                if memory_key:
                    conflicts.setdefault(str(memory_key), []).append(
                        {
                            "id": str(memory_id),
                            "memory_type": str(memory_type),
                            "scope": str(scope or ""),
                        }
                    )
                duplicates.setdefault(str(normalized_content), []).append(str(memory_id))
            conflict_groups = [
                {"memory_key": key, "items": items}
                for key, items in conflicts.items()
                if len(items) > 1
            ]
            duplicate_groups = [
                {"normalized_content": content, "memory_ids": ids}
                for content, ids in duplicates.items()
                if len(ids) > 1
            ]
            run.result_payload = {
                **run.result_payload,
                "expired": expired,
                "reembedded": reembedded,
                "stale_embeddings": stale,
                "conflicting_keys": len(conflict_groups),
                "conflict_groups": conflict_groups[:100],
                "duplicate_content_groups": len(duplicate_groups),
                "duplicate_groups": duplicate_groups[:100],
                "embedding_model": model,
                "embedding_signature": signature,
                "failures": failures[-100:],
            }
            run.status = "FAILED" if failed else "SUCCEEDED"
            run.progress = 100
            run.completed_at = _now()
            run.current_memory_id = None
            if failed:
                run.error = f"{failed} 条记忆检查失败，可重试"
            await self.session.commit()
            await self.session.refresh(run)
            return run
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.session.rollback()
            failed_run = await self.get(run.id)
            failed_run.status = "FAILED"
            failed_run.error = str(exc)[:500]
            failed_run.completed_at = _now()
            await self.session.commit()
            return failed_run


async def execute_memory_embedding(run_id: UUID) -> None:
    async with SessionLocal() as session:
        service = MemoryEmbeddingService(session)
        try:
            from app.services.llm_settings import LLMSettingsService

            provider = await LLMSettingsService(session).get_runtime_embedding_provider()
            await service.execute(run_id, provider)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                run = await service.get(run_id)
                run.status = "FAILED"
                run.error = str(exc)[:500]
                run.completed_at = _now()
                await session.commit()
            except MemoryEmbeddingError:
                return


def schedule_memory_embedding(run_id: UUID) -> None:
    if get_settings().independent_worker:
        return
    current = _active_tasks.get(run_id)
    if current is not None and not current.done():
        return
    task = asyncio.create_task(execute_memory_embedding(run_id))
    _active_tasks[run_id] = task
    task.add_done_callback(lambda _: _active_tasks.pop(run_id, None))


async def recover_interrupted_memory_embeddings() -> list[UUID]:
    if get_settings().independent_worker:
        return []
    async with SessionLocal() as session:
        run_ids = list(
            (
                await session.scalars(
                    select(MemoryEmbeddingRun.id).where(
                        MemoryEmbeddingRun.status.in_(["PENDING", "RUNNING"])
                    )
                )
            ).all()
        )
        if run_ids:
            await session.execute(
                update(MemoryEmbeddingRun)
                .where(MemoryEmbeddingRun.id.in_(run_ids))
                .values(
                    status="PENDING",
                    error="服务重启，任务将从已持久化的记忆检查点恢复",
                )
            )
            await session.commit()
        return run_ids


async def shutdown_memory_embedding_tasks() -> None:
    tasks = list(_active_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_tasks.clear()
