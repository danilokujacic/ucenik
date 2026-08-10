"""Redis-backed rate limiting - fixed window per (client, scope).

Two layers:
- A global per-IP baseline on every request, generous enough not to bother
  normal usage, there to blunt basic abuse/scraping.
- A stricter dedicated limit on login specifically (core.security imports
  this into api/auth.py) - credential-stuffing/brute-force is the higher-risk
  case general API abuse isn't, and pre-auth there's no user id to key on,
  only IP.

Gated by settings.rate_limit_enabled (off in tests - see tests/conftest.py -
a global per-IP limit would otherwise trip against the test suite's own
rapid-fire requests from a single IP under ASGITransport).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ucenik.core.config import settings
from ucenik.core.redis import get_redis
from ucenik.errors.service import RateLimitExceededError

logger = logging.getLogger(__name__)


async def _check_and_increment(key: str, max_requests: int, window_seconds: int) -> None:
    redis = get_redis()
    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, window_seconds)
    if current > max_requests:
        # TTL is the real "seconds left in this fixed window" - read it
        # back rather than assuming window_seconds, since this call could
        # land anywhere inside an already-running window. Redis TTL is -1
        # (no expiry) or -2 (key gone) only in edge cases that shouldn't
        # happen here (expire is always set on the first increment above);
        # fall back to the full window rather than send a nonsensical
        # negative Retry-After if one of those edge cases is ever hit.
        ttl = await redis.ttl(key)
        retry_after = ttl if ttl and ttl > 0 else window_seconds
        raise RateLimitExceededError(
            f"rate limit exceeded: {max_requests} requests per {window_seconds}s", retry_after_seconds=retry_after
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def check_login_rate_limit(request: Request) -> None:
    """FastAPI dependency - call from the login route specifically."""
    if not settings.rate_limit_enabled:
        return
    key = f"ratelimit:login:{_client_ip(request)}"
    await _check_and_increment(key, settings.rate_limit_login_requests_per_minute, 60)


def register_rate_limiting(app: FastAPI) -> None:
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        key = f"ratelimit:global:{_client_ip(request)}"
        try:
            await _check_and_increment(key, settings.rate_limit_requests_per_minute, 60)
        except RateLimitExceededError as exc:
            logger.warning("rate_limit.exceeded", extra={"event": "rate_limit.exceeded", "path": request.url.path})
            headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds is not None else {}
            return JSONResponse(status_code=429, content={"detail": str(exc)}, headers=headers)

        return await call_next(request)
