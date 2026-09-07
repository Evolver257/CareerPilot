"""Subprocess fault injection for isolated tests only."""

import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

from app.models.entities import KnowledgeIndexRun
from app.worker import run_once


async def main():
    schema = os.environ["WORKER_TEST_SCHEMA"]
    if not schema.startswith("test_worker_"):
        raise RuntimeError("Only isolated test schemas allowed")
    engine = create_async_engine(
        os.environ["WORKER_TEST_DATABASE_URL"],
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )

    async def checkpoint(session, work):
        run = await session.get(KnowledgeIndexRun, work.run_id)
        run.status = "RUNNING"
        run.result_payload = {"first_step_committed": True, "effects": 1}
        await session.commit()
        print("CHECKPOINT", flush=True)
        await asyncio.sleep(60)
        return run

    await run_once(engine, handler=checkpoint)


if __name__ == "__main__":
    asyncio.run(main())
