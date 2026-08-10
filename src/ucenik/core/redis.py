import redis.asyncio as redis

from ucenik.core.config import settings

redis_client: redis.Redis | None = None


async def init_redis() -> redis.Redis:
    global redis_client
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return redis_client


async def close_redis() -> None:
    if redis_client is not None:
        await redis_client.aclose()


def get_redis() -> redis.Redis:
    if redis_client is None:
        raise RuntimeError("Redis not initialized")
    return redis_client
