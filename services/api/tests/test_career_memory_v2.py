from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.llm.usage import UsageRecord
from app.models.base import Base
from app.models.entities import AgentMemory, EvaluationRun, MemoryCandidate, User
from app.schemas.evaluations import EvaluationDatasetCreate
from app.schemas.memory import MemoryCreate
from app.services.career_memory import CareerMemoryService
from app.services.evaluations import EvaluationService
from app.services.llm_settings import LLMSettingsService
from app.services.memory_embeddings import MemoryEmbeddingService


class StructuredProvider:
    provider_name = "test"
    model = "test-model"
    embedding_model = "test-embedding"
    embedding_signature = "test-embedding:1024"
    dimensions = 1024

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.last_usage = UsageRecord(prompt_tokens=1, completion_tokens=1, source="test")

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        del text, model
        return [0.0] * self.dimensions

    async def generate_structured(self, prompt, schema, **kwargs):
        del prompt, kwargs
        return schema.model_validate(self.payload)


async def _session() -> tuple[AsyncSession, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return factory(), engine


async def test_v2_llm_candidate_requires_contiguous_source_quote() -> None:
    session, engine = await _session()
    try:
        user = User(email=f"{uuid4()}@example.test", name="Test")
        session.add(user)
        await session.commit()
        provider = StructuredProvider(
            {
                "candidates": [
                    {
                        "memory_type": "SKILL_BACKGROUND",
                        "memory_class": "SEMANTIC",
                        "memory_key": "skill.python",
                        "normalized_content": "用户具有 Python 项目经验",
                        "structured_value": {"name": "Python", "level": "intermediate"},
                        "scope": "backend",
                        "stability": "STABLE",
                        "importance": 0.8,
                        "confidence": 0.95,
                        "source_quote": "我用 Python 做过一个项目",
                        "requires_confirmation": True,
                    }
                ]
            }
        )
        service = CareerMemoryService(session, llm_provider=provider)
        settings = await service.get_settings(user.id)
        settings.enabled = True
        await session.commit()
        candidates = await service.capture_candidates(
            user.id,
            uuid4(),
            uuid4(),
            "我用 Python 做过一个项目，现在想找后端实习。",
        )
        assert candidates == []
        saved = await session.scalar(
            select(AgentMemory).where(
                AgentMemory.user_id == user.id,
                AgentMemory.memory_key == "skill.python",
            )
        )
        assert saved is not None
        assert saved.source_quote == "我用 Python 做过一个项目"
        assert saved.user_confirmed is True

        provider.payload["candidates"][0]["source_quote"] = "我没有说过这句话"
        rejected = await service.capture_candidates(
            user.id,
            uuid4(),
            uuid4(),
            "我用 Python 做过一个项目。",
        )
        assert rejected == []
        assert len(
            list(
                (
                    await session.scalars(
                        select(AgentMemory).where(AgentMemory.user_id == user.id)
                    )
                ).all()
            )
        ) == 1
    finally:
        await session.close()
        await engine.dispose()


async def test_v2_confirmed_update_supersedes_previous_version() -> None:
    session, engine = await _session()
    try:
        user = User(email=f"{uuid4()}@example.test", name="Test")
        session.add(user)
        await session.commit()
        service = CareerMemoryService(session)
        settings = await service.get_settings(user.id)
        settings.enabled = True
        await session.commit()
        old = await service.create(
            MemoryCreate(
                memory_type="CAREER_GOAL",
                content="我想成为 AI Agent 工程师",
                memory_key="career.target_role",
            ),
            user_id=user.id,
        )
        candidates = await service.capture_candidates(
            user.id,
            uuid4(),
            uuid4(),
            "我的职业目标是成为产品经理。",
        )
        assert candidates == []
        new = await session.scalar(
            select(AgentMemory).where(
                AgentMemory.user_id == user.id,
                AgentMemory.memory_key == "career.target_role",
                AgentMemory.status == "ACTIVE",
            )
        )
        assert new is not None
        await session.refresh(old)
        assert old.status == "SUPERSEDED"
        assert new.supersedes_id == old.id
        assert await service.retrieve(user.id, "职业目标") == [new]
    finally:
        await session.close()
        await engine.dispose()


async def test_rule_memory_policy_and_attribute_keys() -> None:
    session, engine = await _session()
    try:
        user = User(email=f"{uuid4()}@example.test", name="Test")
        session.add(user)
        await session.commit()
        service = CareerMemoryService(session)
        settings = await service.get_settings(user.id)
        settings.enabled = True
        settings.auto_save_non_sensitive = True
        await session.commit()

        preference_candidates = await service.capture_candidates(
            user.id, uuid4(), uuid4(), "我偏好北京线下岗位。"
        )
        assert preference_candidates == []
        preference = await session.scalar(
            select(AgentMemory).where(
                AgentMemory.user_id == user.id,
                AgentMemory.memory_key == "preference.location",
            )
        )
        assert preference is not None
        assert preference.user_confirmed is True

        await service.capture_candidates(user.id, uuid4(), uuid4(), "我会 Python 开发。")
        await service.capture_candidates(user.id, uuid4(), uuid4(), "我熟悉 FastAPI 框架。")
        skill_items = list(
            (
                await session.scalars(
                    select(AgentMemory).where(
                        AgentMemory.user_id == user.id,
                        AgentMemory.memory_type == "SKILL_BACKGROUND",
                    )
                )
            ).all()
        )
        assert {item.memory_key for item in skill_items} == {"skill.python", "skill.fastapi"}
        assert not list(
            (
                await session.scalars(
                    select(MemoryCandidate).where(
                        MemoryCandidate.user_id == user.id,
                        MemoryCandidate.memory_type == "SKILL_BACKGROUND",
                    )
                )
            ).all()
        )
    finally:
        await session.close()
        await engine.dispose()


async def test_restore_preserves_expired_status() -> None:
    session, engine = await _session()
    try:
        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        user = User(email=settings.default_user_email, name="Test")
        session.add(user)
        await session.commit()
        service = CareerMemoryService(session, settings=settings)
        item = await service.create(
            MemoryCreate(memory_type="SKILL_BACKGROUND", content="我会 Python"),
            user_id=user.id,
        )
        await service.mark_outdated(item.id)
        await service.delete(item.id)
        restored = await service.restore(item.id)
        assert restored.status == "EXPIRED"
        assert restored.deleted_at is None
        assert restored.deleted_from_status is None
    finally:
        await session.close()
        await engine.dispose()


async def test_memory_embedding_run_persists_progress_and_vector() -> None:
    session, engine = await _session()
    try:
        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        user = User(email=settings.default_user_email, name=settings.default_user_name)
        session.add(user)
        await session.commit()
        service = CareerMemoryService(session, settings=settings)
        await service.create(
            MemoryCreate(memory_type="SKILL_BACKGROUND", content="我会 Python"),
            user_id=user.id,
        )
        provider = StructuredProvider({"candidates": []})
        runs = MemoryEmbeddingService(session, provider, settings)
        run = await runs.create(mode="incremental")
        assert run.total == 1
        completed = await runs.execute(run.id)
        assert completed.status == "SUCCEEDED"
        assert completed.progress == 100
        assert completed.succeeded == 1
        health = await runs.health()
        assert health["status"] == "ready"
        assert health["embedded"] == 1
        stored = await session.scalar(select(AgentMemory).where(AgentMemory.user_id == user.id))
        assert stored is not None
        assert stored.embedding_signature == provider.embedding_signature
    finally:
        await session.close()
        await engine.dispose()


async def test_memory_maintenance_expires_due_items_and_reports_hygiene() -> None:
    session, engine = await _session()
    try:
        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        user = User(email=settings.default_user_email, name=settings.default_user_name)
        session.add(user)
        await session.commit()
        service = CareerMemoryService(session, settings=settings)
        item = await service.create(
            MemoryCreate(memory_type="SKILL_BACKGROUND", content="我会 Python"),
            user_id=user.id,
        )
        item.valid_until = item.created_at
        await session.commit()
        provider = StructuredProvider({"candidates": []})
        runs = MemoryEmbeddingService(session, provider, settings)
        run = await runs.create_maintenance()
        completed = await runs.execute(run.id, provider)
        await session.refresh(item)
        assert completed.status == "SUCCEEDED"
        assert completed.result_payload["expired"] == 1
        assert completed.result_payload["reembedded"] == 1
        assert completed.result_payload["stale_embeddings"] == 0
        assert item.status == "EXPIRED"
    finally:
        await session.close()
        await engine.dispose()


async def test_memory_maintenance_conflicts_require_explicit_resolution() -> None:
    session, engine = await _session()
    try:
        settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
        user = User(email=settings.default_user_email, name=settings.default_user_name)
        session.add(user)
        await session.commit()
        service = CareerMemoryService(session, settings=settings)
        first = await service.create(
            MemoryCreate(
                memory_type="SKILL_BACKGROUND",
                memory_key="skill.runtime",
                content="我会 Python",
            ),
            user_id=user.id,
        )
        second = await service.create(
            MemoryCreate(
                memory_type="SKILL_BACKGROUND",
                memory_key="skill.runtime",
                content="我会 Go",
            ),
            user_id=user.id,
        )
        runs = MemoryEmbeddingService(session, StructuredProvider({"candidates": []}), settings)
        run = await runs.create_maintenance()
        completed = await runs.execute(run.id, runs.embedding_provider)
        assert len(completed.result_payload["conflict_groups"]) == 1
        resolved = await runs.resolve_maintenance_action(
            run.id,
            action="supersede_conflict",
            source_memory_id=second.id,
            target_memory_id=first.id,
        )
        assert resolved.result_payload["resolved_actions"][-1]["action"] == "supersede_conflict"
        await session.refresh(second)
        assert second.status == "SUPERSEDED"
    finally:
        await session.close()
        await engine.dispose()


async def test_online_memory_evaluation_isolated_and_records_real_observations(monkeypatch) -> None:
    session, engine = await _session()
    try:
        provider = StructuredProvider({"candidates": []})

        async def runtime_provider(self):
            return provider

        async def runtime_embedding_provider(self):
            return provider

        monkeypatch.setattr(LLMSettingsService, "get_runtime_provider", runtime_provider)
        monkeypatch.setattr(
            LLMSettingsService,
            "get_runtime_embedding_provider",
            runtime_embedding_provider,
        )
        service = EvaluationService(session)
        dataset = await service.create_dataset(
            EvaluationDatasetCreate(
                name="online memory test",
                suite="memory",
                version="online-test-v1",
                label_status="seed_requires_dual_review",
                cases=[
                    {
                        "case_id": "online-skill",
                        "dataset_version": "online-test-v1",
                        "split": "dev",
                        "category": "extraction",
                        "user_query": "我会 Python",
                        "expected_candidates": [
                            {
                                "memory_type": "SKILL_BACKGROUND",
                                "memory_key": "skill.python",
                                "source_quote": "我会 Python",
                            }
                        ],
                    },
                    {
                        "case_id": "online-retrieve",
                        "dataset_version": "online-test-v1",
                        "split": "test",
                        "category": "retrieval",
                        "user_query": "我想申请后端实习",
                        "expected_retrieval_memory_ids": ["memory-python"],
                    },
                ],
            )
        )
        run = EvaluationRun(
            dataset_id=dataset.id,
            status="PENDING",
            configuration={
                "execution_mode": "online",
                "bootstrap_memories": [
                    {
                        "id": "memory-python",
                        "memory_type": "SKILL_BACKGROUND",
                        "content": "我会 Python",
                    }
                ],
                "seed": 20260908,
            },
            progress_total=2,
        )
        session.add(run)
        await session.flush()
        completed = await service.execute(run.id)
        assert completed.status == "SUCCEEDED"
        assert completed.result["online_execution"]["isolated_user"] is True
        assert completed.result["online_execution"]["bootstrap_count"] == 1
        assert completed.result["summary"]["sensitive_memory_save_violation"] == 0
    finally:
        await session.close()
        await engine.dispose()


async def test_memory_maintenance_api_is_durable(client) -> None:
    await client.patch("/api/career-memory/settings", json={"enabled": True})
    response = await client.post("/api/career-memory/maintenance-runs")
    assert response.status_code == 201
    assert response.json()["mode"] == "maintenance"


async def test_v2_api_exposes_structured_fields_and_lifecycle_controls(client) -> None:
    await client.patch(
        "/api/career-memory/settings",
        json={"enabled": True, "allow_unconfirmed_context": True},
    )
    response = await client.post(
        "/api/career-memory/items",
        json={
            "memory_type": "SKILL_BACKGROUND",
            "memory_key": "skill.python",
            "content": "我会 Python",
            "structured_value": {"name": "Python", "level": "basic"},
            "source_quote": "我会 Python",
        },
    )
    assert response.status_code == 201
    item = response.json()
    assert item["memory_key"] == "skill.python"
    assert item["structured_value"]["level"] == "basic"
    assert item["status"] == "ACTIVE"

    pinned = await client.patch(
        f"/api/career-memory/items/{item['id']}", json={"pinned": True}
    )
    assert pinned.json()["pinned"] is True
    outdated = await client.post(f"/api/career-memory/items/{item['id']}/outdated")
    assert outdated.json()["status"] == "EXPIRED"
    deleted = await client.delete(f"/api/career-memory/items/{item['id']}")
    assert deleted.status_code == 204
    recycle_bin = await client.get("/api/career-memory/items?status=DELETED")
    assert recycle_bin.status_code == 200
    assert recycle_bin.json()["items"][0]["status"] == "DELETED"
    history = await client.get(f"/api/career-memory/items/{item['id']}/history")
    assert history.status_code == 200
    assert len(history.json()) == 1
    health = await client.get("/api/career-memory/embedding-health")
    assert health.status_code == 200
    assert health.json()["embedding_dimensions"] == 1024
