from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Job

LifecycleStatus = Literal["active", "possibly_expired", "expired"]


def derive_lifecycle(
    last_collected_at: datetime | None,
    *,
    now: datetime | None = None,
    possibly_expired_days: int = 14,
    expired_days: int = 30,
) -> LifecycleStatus:
    if last_collected_at is None:
        return "possibly_expired"
    current = now or datetime.now(UTC)
    collected = (
        last_collected_at if last_collected_at.tzinfo else last_collected_at.replace(tzinfo=UTC)
    )
    age = current - collected
    if age >= timedelta(days=expired_days):
        return "expired"
    if age >= timedelta(days=possibly_expired_days):
        return "possibly_expired"
    return "active"


async def refresh_lifecycle(
    session: AsyncSession,
    *,
    possibly_expired_days: int = 14,
    expired_days: int = 30,
    now: datetime | None = None,
) -> int:
    current = now or datetime.now(UTC)
    expired_cutoff = current - timedelta(days=expired_days)
    possible_cutoff = current - timedelta(days=possibly_expired_days)
    total = 0
    for statement in (
        update(Job)
        .where(Job.last_collected_at < expired_cutoff)
        .values(lifecycle_status="expired"),
        update(Job)
        .where(Job.last_collected_at >= expired_cutoff, Job.last_collected_at < possible_cutoff)
        .values(lifecycle_status="possibly_expired"),
        update(Job)
        .where(Job.last_collected_at >= possible_cutoff)
        .values(lifecycle_status="active"),
    ):
        result = await session.execute(statement)
        total += int(result.rowcount or 0)
    await session.commit()
    return total
