"""Token-usage quota, backed by Redis (roadmap §6).

Originally scoped to Phase 5 (Tutor chat), pulled forward to cover the one
LLM-consuming flow that exists today - rag/contextualizer.py, called from
document ingest. Wired into chat the same way once that exists: check_quota()
before the call, record_usage() after.

Window: per-user, per-UTC-day. Resets itself via Redis TTL - no cron/cleanup
job needed, the key just stops existing.
"""

import logging
from datetime import UTC, datetime, timedelta

from ucenik.core.config import settings
from ucenik.core.redis import get_redis
from ucenik.errors.service import QuotaExceededError

logger = logging.getLogger(__name__)

_DAY_TTL_SECONDS = 60 * 60 * 25  # 25h safety margin over a calendar day


def _quota_key(user_id: str) -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"quota:{user_id}:{today}"


def next_reset_at() -> datetime:
    """Next UTC midnight - when today's quota key naturally stops existing.
    Used by api/users.py's GET /users/me/quota, so a user has something
    more informative than "you'll find out when the 429 stops."
    """
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).date()
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=UTC)


async def get_usage(user_id: str) -> int:
    """Read-only: today's running token total. No logging, unlike
    check_quota()/record_usage() - this isn't itself a quota-consuming
    action, just an inspection (see api/users.py's quota endpoint).
    """
    redis = get_redis()
    used_raw = await redis.get(_quota_key(user_id))
    return int(used_raw) if used_raw is not None else 0


async def check_quota(user_id: str) -> None:
    """Raises QuotaExceededError if the user has already hit their daily
    token limit. Call BEFORE making an LLM call that would consume more -
    this only checks the counter, it doesn't reserve/increment it.
    """
    redis = get_redis()
    used_raw = await redis.get(_quota_key(user_id))
    used_tokens = int(used_raw) if used_raw is not None else 0

    logger.info(
        "quota.check",
        extra={
            "event": "quota.check",
            "user_id": user_id,
            "used_tokens": used_tokens,
            "limit": settings.max_quota,
        },
    )

    if used_tokens >= settings.max_quota:
        retry_after = int((next_reset_at() - datetime.now(UTC)).total_seconds())
        raise QuotaExceededError(user_id, used_tokens, settings.max_quota, retry_after_seconds=retry_after)


async def record_usage(user_id: str, tokens: int) -> int:
    """Increments today's usage counter, returns the new running total."""
    redis = get_redis()
    key = _quota_key(user_id)
    new_total = await redis.incrby(key, tokens)
    if new_total == tokens:  # first write for this key today - start its TTL
        await redis.expire(key, _DAY_TTL_SECONDS)

    logger.info(
        "quota.usage",
        extra={
            "event": "quota.usage",
            "user_id": user_id,
            "tokens_added": tokens,
            "used_tokens": new_total,
            "limit": settings.max_quota,
        },
    )
    return new_total
