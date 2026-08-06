"""Thin client to the self-hosted LLM proxy (§13).

Never call a provider SDK (openai, anthropic, ...) directly anywhere else in
the codebase - everything routes through here, so swapping/adding providers
behind the proxy never touches application code.

TODO: the proxy itself doesn't exist/run yet. This assumes an OpenAI-compatible
contract (POST {llm_proxy_url}/chat/completions, Bearer auth, standard
choices[0].message.content response shape) as a placeholder - confirm/adjust
against the real proxy once it's up.
"""

import logging
from typing import Any

import httpx

from ucenik.core.config import settings
from ucenik.core.resilience import CircuitBreaker, retry_with_backoff

logger = logging.getLogger(__name__)

# Module-level: shared across calls within this process so repeated failures
# actually trip the breaker instead of each call getting a fresh one.
_circuit_breaker = CircuitBreaker(failure_threshold=5, reset_timeout=30.0)


class LLMProxyError(Exception):
    """Raised when the proxy call fails after retries/circuit-breaking."""


async def complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> str:
    """Send a chat-completion request to the proxy and return the assistant's
    reply text. Retries transient HTTP failures with backoff, and short-circuits
    via a circuit breaker once the proxy looks consistently down.
    """
    payload: dict[str, Any] = {
        "model": model or settings.llm_proxy_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    async def _call() -> str:
        async with httpx.AsyncClient(
            base_url=settings.llm_proxy_url,
            timeout=settings.llm_proxy_timeout_seconds,
        ) as client:
            response = await client.post(
                "/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.llm_proxy_api_key}"},
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    try:
        return await _circuit_breaker.call(
            lambda: retry_with_backoff(_call, attempts=3, retry_on=(httpx.HTTPError,))
        )
    except Exception as exc:
        logger.error("LLM proxy call failed: %s", exc)
        raise LLMProxyError("failed to reach the LLM proxy") from exc
