"""Thin client to the self-hosted LLM proxy (§13, src/ucenik/llm_proxy/).

Never call a provider SDK (openai, anthropic, groq, ...) directly anywhere
else in the codebase - everything routes through here, so this app never
needs to know which real provider is behind the proxy or what its wire
format looks like (currently Groq, via an OpenAI-compatible relay - see
llm_proxy/main.py - but swapping providers only ever touches that one
service, never this client or its callers).

Contract this client speaks (and the proxy implements): OpenAI-compatible
POST {llm_proxy_url}/chat/completions, Bearer auth, standard
choices[0].message.content response shape, usage: {prompt_tokens,
completion_tokens, total_tokens}; streaming via `stream: true` SSE, same
shape as stream_complete()'s docstring describes.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
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


def _auth_headers() -> dict[str, str]:
    """Omit Authorization entirely when no API key is configured (the
    LLM_PROXY_API_KEY="" default - see .env.example) rather than sending
    "Bearer " with nothing after it: httpcore's header validation rejects a
    trailing-whitespace header value outright (LocalProtocolError, not even
    a request that reaches the proxy) - found by actually exercising
    stream_complete() against a real server, since complete() only ever
    runs mocked in tests (rag/contextualizer.complete is always patched).
    """
    if not settings.llm_proxy_api_key:
        return {}
    return {"Authorization": f"Bearer {settings.llm_proxy_api_key}"}


@dataclass
class CompletionResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str


async def complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> CompletionResult:
    """Send a chat-completion request to the proxy. Retries transient HTTP
    failures with backoff, and short-circuits via a circuit breaker once the
    proxy looks consistently down. Every call (success or failure) emits a
    structured "llm.call" log event - see docs/observability.md.
    """
    resolved_model = model or settings.llm_proxy_model
    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    async def _call() -> CompletionResult:
        async with httpx.AsyncClient(
            base_url=settings.llm_proxy_url,
            timeout=settings.llm_proxy_timeout_seconds,
        ) as client:
            response = await client.post("/chat/completions", json=payload, headers=_auth_headers())
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage", {})
            return CompletionResult(
                content=data["choices"][0]["message"]["content"],
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
                model=resolved_model,
            )

    start = time.perf_counter()
    try:
        result = await _circuit_breaker.call(lambda: retry_with_backoff(_call, attempts=3, retry_on=(httpx.HTTPError,)))
    except Exception as exc:
        logger.error(
            "llm.call",
            extra={
                "event": "llm.call",
                "model": resolved_model,
                "success": False,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                "error": str(exc),
            },
        )
        raise LLMProxyError("failed to reach the LLM proxy") from exc

    logger.info(
        "llm.call",
        extra={
            "event": "llm.call",
            "model": result.model,
            "success": True,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
        },
    )
    return result


@dataclass
class UsageInfo:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class StreamedCompletion:
    """Async-iterate to get content deltas as they arrive; `.usage` and
    `.model` are populated once iteration is exhausted (None before that -
    the proxy's final SSE chunk is what carries usage, so there's nothing to
    report until the stream actually ends). Returned by stream_complete().
    """

    def __init__(self, model: str):
        self.model = model
        self.usage: UsageInfo | None = None
        self._agen: AsyncGenerator[str] | None = None

    def __aiter__(self) -> StreamedCompletion:
        return self

    async def __anext__(self) -> str:
        assert self._agen is not None
        return await self._agen.__anext__()


async def stream_complete(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> StreamedCompletion:
    """Streaming counterpart to complete() - for Tutor chat (rag/generator.py),
    where the answer needs to reach the browser token-by-token via SSE
    instead of waiting for the whole thing.

    Resilience here is deliberately narrower than complete()'s: retrying a
    request-response call is safe (nothing has been sent to the caller yet
    either way), but retrying mid-stream is not - some tokens may already
    have been forwarded to the browser, so a retry would replay/duplicate
    content instead of cleanly recovering. So: the circuit breaker still
    fails fast up front, and the connect-and-first-chunk phase still retries
    with backoff same as complete() - but the moment a single token has been
    yielded to the caller, any further failure propagates immediately as
    LLMProxyError instead of retrying.

    Assumes the proxy speaks OpenAI-compatible SSE streaming: `data: {...}`
    lines with `choices[0].delta.content`, a final `data: [DONE]`, and (with
    `stream_options.include_usage`) one chunk carrying a top-level `usage`
    object - same placeholder-contract caveat as complete(), see module
    docstring.
    """
    resolved_model = model or settings.llm_proxy_model
    payload: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    result = StreamedCompletion(resolved_model)

    async def _generate() -> AsyncGenerator[str]:
        if _circuit_breaker.is_open:
            raise LLMProxyError("LLM proxy circuit breaker is open - failing fast")

        start = time.perf_counter()
        yielded_any = False
        attempts = 3
        last_exc: httpx.HTTPError | None = None

        for attempt in range(attempts):
            try:
                async with (
                    httpx.AsyncClient(
                        base_url=settings.llm_proxy_url,
                        timeout=settings.llm_proxy_timeout_seconds,
                    ) as client,
                    client.stream("POST", "/chat/completions", json=payload, headers=_auth_headers()) as response,
                ):
                    response.raise_for_status()
                    usage: dict[str, int] | None = None
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        chunk = json.loads(data)
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        choices = chunk.get("choices") or [{}]
                        delta_content = choices[0].get("delta", {}).get("content")
                        if delta_content:
                            yielded_any = True
                            yield delta_content

                result.usage = UsageInfo(
                    prompt_tokens=(usage or {}).get("prompt_tokens", 0),
                    completion_tokens=(usage or {}).get("completion_tokens", 0),
                    total_tokens=(usage or {}).get("total_tokens", 0),
                )
                _circuit_breaker.record_success()
                logger.info(
                    "llm.call",
                    extra={
                        "event": "llm.call",
                        "model": resolved_model,
                        "success": True,
                        "streamed": True,
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                        **({"total_tokens": result.usage.total_tokens} if result.usage else {}),
                    },
                )
                return
            except httpx.HTTPError as exc:
                last_exc = exc
                if yielded_any or attempt == attempts - 1:
                    break
                delay = min(0.5 * (2**attempt), 8.0)
                logger.warning(
                    "retrying LLM proxy stream connect after failure (attempt %d/%d): %s",
                    attempt + 1,
                    attempts,
                    exc,
                )
                await asyncio.sleep(delay)

        _circuit_breaker.record_failure()
        logger.error(
            "llm.call",
            extra={
                "event": "llm.call",
                "model": resolved_model,
                "success": False,
                "streamed": True,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                "error": str(last_exc),
            },
        )
        raise LLMProxyError("failed to reach the LLM proxy") from last_exc

    result._agen = _generate()
    return result
