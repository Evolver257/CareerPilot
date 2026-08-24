from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db

router = APIRouter(tags=["health"])


async def _redis_status() -> str:
    client = Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=0.3,
        socket_timeout=0.3,
    )
    try:
        await client.ping()
        return "ok"
    except Exception:
        return "unavailable"
    finally:
        await client.aclose()


@router.get("/health")
async def health_check(session: AsyncSession = Depends(get_db)) -> dict[str, object]:
    database_status = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"

    redis_status = await _redis_status()
    overall = "ok" if database_status == "ok" and redis_status == "ok" else "degraded"
    return {
        "status": overall,
        "service": "careerpilot-api",
        "dependencies": {"database": database_status, "redis": redis_status},
    }
