"""Transactional dispatch; PostgreSQL is the queue, not a second broker."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.models.work import BackgroundWork


async def enqueue_work(session, kind, run_id, *, retry=False, delay_seconds=0):
    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    now = datetime.now(UTC)
    stmt = insert(BackgroundWork).values(
        id=uuid4(),
        kind=kind,
        run_id=run_id,
        status="PENDING",
        attempts=0,
        generation=0,
        available_at=now + timedelta(seconds=max(0, delay_seconds)),
        created_at=now,
        updated_at=now,
    )
    if retry:
        stmt = stmt.on_conflict_do_update(
            index_elements=["kind", "run_id"],
            set_={
                "status": "PENDING",
                "attempts": 0,
                "error": None,
                "updated_at": now,
                "generation": BackgroundWork.generation + 1,
                "available_at": now,
            },
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=["kind", "run_id"])
    await session.execute(stmt)
