"""Admin-managed IP blocklist (docs/security-hardening.md item 8) -
Redis-backed, checked by core/rate_limit.py's middleware before the actual
rate-limit counting logic runs, so a blocked IP costs one cheap Redis
lookup and a 403, not a full counted request.

Depends on core/rate_limit.py's _client_ip() actually reflecting the real
client (docs/security-hardening.md item 6) - blocking "by IP" only means
something once that IP is the real caller's, not nginx's own container IP.

Distinct from rate limiting: rate limiting throttles everyone, temporarily,
uniformly. This is a manual/targeted block - permanent by default, or
time-boxed if an admin sets a TTL - for a specific IP an admin has decided
should be denied outright, not just slowed down.
"""

from pydantic import BaseModel

from ucenik.core.redis import get_redis

_KEY_PREFIX = "ip_blocklist:"


def _key(ip: str) -> str:
    return f"{_KEY_PREFIX}{ip}"


class BlockedIp(BaseModel):
    ip: str
    reason: str
    ttl_seconds: int | None  # remaining, at read time - None means no expiry (permanent)


async def block_ip(ip: str, reason: str, ttl_seconds: int | None = None) -> None:
    """Adds `ip` to the blocklist. `ttl_seconds=None` blocks it permanently
    (until explicitly unblocked); otherwise the block expires on its own,
    same self-cleaning pattern as core/quota.py's daily counters - no
    separate cleanup job needed either way.
    """
    redis = get_redis()
    if ttl_seconds is not None:
        await redis.set(_key(ip), reason, ex=ttl_seconds)
    else:
        await redis.set(_key(ip), reason)


async def unblock_ip(ip: str) -> None:
    await get_redis().delete(_key(ip))


async def is_ip_blocked(ip: str) -> bool:
    """Called on every request (core/rate_limit.py) - a single Redis GET,
    same cost class as the rate-limit counter check it runs alongside.
    """
    return await get_redis().get(_key(ip)) is not None


async def list_blocked_ips() -> list[BlockedIp]:
    """Admin listing (api/admin_ip_blocklist.py) - uses SCAN, not KEYS, so
    this doesn't block Redis on a large keyspace; blocklist entries are
    expected to be a short, deliberately-curated list, not a high-volume
    key pattern, but SCAN costs nothing extra to use correctly regardless.
    """
    redis = get_redis()
    entries: list[BlockedIp] = []
    async for key in redis.scan_iter(match=f"{_KEY_PREFIX}*"):
        ip = key.removeprefix(_KEY_PREFIX)
        reason, ttl = await redis.get(key), await redis.ttl(key)
        if reason is None:
            continue  # expired between the SCAN and this GET - skip it
        entries.append(BlockedIp(ip=ip, reason=reason, ttl_seconds=ttl if ttl and ttl > 0 else None))
    return entries
