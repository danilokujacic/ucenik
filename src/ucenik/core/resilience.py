"""Generic resilience primitives for wrapping flaky outbound calls (§8).

Nothing here knows about the LLM proxy specifically - `llm/proxy_client.py`
composes these around its HTTP call. In-memory only: state is per-process,
not shared across workers/replicas.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised instead of attempting a call while the circuit is open."""


class CircuitBreaker:
    """Three states:

    - closed: calls go through normally, failures are counted.
    - open: once `failure_threshold` consecutive failures happen, calls fail
      fast with CircuitOpenError (no network round trip) until `reset_timeout`
      elapses.
    - half-open: after the cooldown, the next call is let through as a trial;
      success closes the circuit, failure re-opens it for another cooldown.
    """

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._failure_count = 0
        self._opened_at: float | None = None

    @property
    def _is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.reset_timeout:
            return False  # cooldown elapsed -> half-open, let a trial call through
        return True

    def _on_success(self) -> None:
        self._failure_count = 0
        self._opened_at = None

    def _on_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        """Public read-only check - lets a caller fail fast on its own terms
        without going through .call(), for cases .call()'s single-awaitable
        shape doesn't fit (e.g. rag/generator.py's streaming completion,
        where a retry mid-stream would resend already-forwarded tokens)."""
        return self._is_open

    def record_success(self) -> None:
        self._on_success()

    def record_failure(self) -> None:
        self._on_failure()

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        if self._is_open:
            raise CircuitOpenError("circuit breaker is open")
        try:
            result = await fn()
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> T:
    """Retries `fn` with exponential backoff (base_delay * 2**attempt, capped
    at max_delay). Only exceptions matching `retry_on` are retried - anything
    else propagates immediately.
    """
    last_exc: Exception
    for attempt in range(attempts):
        try:
            return await fn()
        except retry_on as exc:
            last_exc = exc
            if attempt == attempts - 1:
                break
            delay = min(base_delay * (2**attempt), max_delay)
            logger.warning("retrying after failure (attempt %d/%d): %s", attempt + 1, attempts, exc)
            await asyncio.sleep(delay)
    raise last_exc
