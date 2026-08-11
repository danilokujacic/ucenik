"""Redis-backed rate limiting - fixed window per (client, scope).

Three layers, in the order the middleware below applies them:
- The IP blocklist (services/ip_blocklist.py) - an explicit, admin-managed
  deny, checked first and unconditionally (not gated by
  settings.rate_limit_enabled - blocking a specific bad actor is a
  different concern than the general throttle, and should still apply even
  if that's toggled off). Empty by default, so this is a no-op cost (one
  Redis GET) for everyone not on it.
- A global per-IP baseline on every request, generous enough not to bother
  normal usage, there to blunt basic abuse/scraping.
- A stricter dedicated limit on login specifically (core.security imports
  this into api/auth.py) - credential-stuffing/brute-force is the higher-risk
  case general API abuse isn't, and pre-auth there's no user id to key on,
  only IP.

The latter two are gated by settings.rate_limit_enabled (off in tests - see
tests/conftest.py - a global per-IP limit would otherwise trip against the
test suite's own rapid-fire requests from a single IP under ASGITransport).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ucenik.core.config import settings
from ucenik.core.redis import get_redis
from ucenik.errors.service import RateLimitExceededError
from ucenik.services.ip_blocklist import is_ip_blocked

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
    """request.client.host is the app's own view of who it's talking to -
    in prod that's nginx (docker-compose.prod.yaml's `nginx-certbot`), not
    the real client, UNLESS uvicorn's ProxyHeadersMiddleware has rewritten
    it from X-Forwarded-For first. That rewrite is enabled by the
    Dockerfile's --forwarded-allow-ips=* flag (see its comment for the full
    story) - without it, every request here would resolve to nginx's own
    container IP, and this whole module would be rate-limiting one "client"
    (nginx) instead of real ones. No header-parsing needed on this end -
    by the time Starlette hands us `request`, the substitution already
    happened.
    """
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
        client_ip = _client_ip(request)
        if await is_ip_blocked(client_ip):
            # Deliberately checked before routing - this also blocks an
            # admin trying to reach api/admin_ip_blocklist.py's own DELETE
            # endpoint from the IP they just blocked. That's an accepted
            # self-lockout risk inherent to blocking at this layer (an
            # nginx-level `deny` would have the identical problem) - the
            # escape hatch is direct Redis access
            # (`redis-cli DEL ip_blocklist:<ip>`), not another API call.
            logger.warning("rate_limit.blocked_ip", extra={"event": "rate_limit.blocked_ip", "path": request.url.path})
            return JSONResponse(status_code=403, content={"detail": "forbidden"})

        if not settings.rate_limit_enabled:
            return await call_next(request)

        key = f"ratelimit:global:{client_ip}"
        try:
            await _check_and_increment(key, settings.rate_limit_requests_per_minute, 60)
        except RateLimitExceededError as exc:
            logger.warning("rate_limit.exceeded", extra={"event": "rate_limit.exceeded", "path": request.url.path})
            headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds is not None else {}
            return JSONResponse(status_code=429, content={"detail": str(exc)}, headers=headers)

        return await call_next(request)
