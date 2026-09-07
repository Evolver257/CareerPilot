from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.entities import User
from app.schemas.memory import MemoryCreate, MemorySettingsUpdate
from app.services.career_memory import CareerMemoryService


async def test_memory_defaults_to_off_and_supports_crud(client) -> None:
    settings = await client.get("/api/career-memory/settings")
    assert settings.status_code == 200
    assert settings.json()["enabled"] is False

    updated = await client.patch(
        "/api/career-memory/settings",
        json={"enabled": True, "retention_days": 90},
    )
    assert updated.status_code == 200
    assert updated.json()["retention_days"] == 90

    created = await client.post(
        "/api/career-memory/items",
        json={"memory_type": "JOB_PREFERENCE", "content": "我偏好北京的 AI Agent 实习"},
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]
    assert created.json()["user_confirmed"] is True

    duplicate = await client.post(
        "/api/career-memory/items",
        json={"memory_type": "JOB_PREFERENCE", "content": "我偏好北京的 AI Agent 实习"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == memory_id

    listed = await client.get("/api/career-memory/items?query=agent")
    assert listed.json()["total"] == 1

    deleted = await client.delete(f"/api/career-memory/items/{memory_id}")
    assert deleted.status_code == 204
    assert (await client.get("/api/career-memory/items")).json()["total"] == 0

    restored = await client.post(f"/api/career-memory/items/{memory_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None

    exported = await client.get("/api/career-memory/export")
    assert exported.status_code == 200
    assert len(exported.json()["memories"]) == 1


async def test_memory_rejects_sensitive_values(client) -> None:
    response = await client.post(
        "/api/career-memory/items",
        json={
            "memory_type": "USER_CONFIRMED_FACT",
            "content": "api_key: sk-secret-value-1234567890",
        },
    )
    assert response.status_code == 422
    assert "不能保存" in response.json()["detail"]
    assert (await client.get("/api/career-memory/items")).json()["total"] == 0


async def test_advisor_creates_confirmable_memory_candidate(client) -> None:
    await client.patch("/api/career-memory/settings", json={"enabled": True})
    created = await client.post("/api/career-advisor/sessions", json={})
    session_id = created.json()["id"]
    response = await client.post(
        f"/api/career-advisor/sessions/{session_id}/messages",
        json={"content": "我的职业目标是成为 AI Agent 工程师。请给我一点建议。"},
    )
    assert response.status_code == 201

    candidates = await client.get("/api/career-memory/candidates")
    assert candidates.status_code == 200
    assert candidates.json()["total"] == 1
    candidate = candidates.json()["items"][0]
    assert candidate["memory_type"] == "CAREER_GOAL"

    accepted = await client.post(
        f"/api/career-memory/candidates/{candidate['id']}/accept"
    )
    assert accepted.status_code == 200
    assert accepted.json()["user_confirmed"] is True


async def test_memory_retrieval_is_user_isolated_and_pause_is_effective() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        first = User(email="first@example.test", name="First")
        second = User(email="second@example.test", name="Second")
        session.add_all([first, second])
        await session.commit()
        service = CareerMemoryService(session)
        await service.update_settings(MemorySettingsUpdate(enabled=False))
        await service.get_settings(first.id)
        first_settings = await service.get_settings(first.id)
        first_settings.enabled = True
        second_settings = await service.get_settings(second.id)
        second_settings.enabled = True
        await session.commit()
        await service.create(
            MemoryCreate(memory_type="CAREER_GOAL", content="我想成为 Agent 工程师"),
            user_id=first.id,
        )
        assert len(await service.retrieve(first.id, "Agent 工程师")) == 1
        assert await service.retrieve(second.id, "Agent 工程师") == []
        first_settings.enabled = False
        await session.commit()
        assert await service.retrieve(first.id, "Agent 工程师") == []
    await engine.dispose()


async def test_memory_auto_save_is_limited_and_conflicts_still_require_confirmation(
    client,
) -> None:
    await client.patch(
        "/api/career-memory/settings",
        json={"enabled": True, "auto_save_non_sensitive": True},
    )
    created = await client.post("/api/career-advisor/sessions", json={})
    session_id = created.json()["id"]
    await client.post(
        f"/api/career-advisor/sessions/{session_id}/messages",
        json={"content": "我做过校园活动策划。"},
    )
    memories = await client.get("/api/career-memory/items")
    assert memories.json()["total"] == 1
    assert memories.json()["items"][0]["user_confirmed"] is False

    await client.post(
        f"/api/career-advisor/sessions/{session_id}/messages",
        json={"content": "我做过社区志愿服务。"},
    )
    candidates = await client.get("/api/career-memory/candidates")
    assert candidates.json()["total"] == 1
    assert "冲突" in candidates.json()["items"][0]["reason"]

    await client.post(
        f"/api/career-advisor/sessions/{session_id}/messages",
        json={"content": "我的职业目标是成为产品经理。"},
    )
    candidates = await client.get("/api/career-memory/candidates")
    assert candidates.json()["total"] == 2
