import asyncio
import logging
import os

from redis.asyncio import Redis

logger = logging.getLogger("careerpilot.worker")


async def run() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = Redis.from_url(redis_url)
    try:
        await client.ping()
        logger.info("worker_ready redis_url=%s", redis_url)
        await asyncio.Event().wait()
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(run())
