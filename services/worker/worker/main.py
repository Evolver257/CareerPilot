import asyncio
import os

from redis.asyncio import Redis


async def run() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    client = Redis.from_url(redis_url)
    try:
        await client.ping()
        print("CareerPilot worker is ready")
        await asyncio.Event().wait()
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(run())
