"""Self-hosted OpenAI-compatible LLM proxy (§Phase 4, docs/roadmap.md) -
this IS the proxy `llm/proxy_client.py`'s module docstring used to describe
as a TODO/placeholder. Runs as its own service - own container, own port -
so the main app never talks to a provider SDK directly; it only ever knows
the OpenAI-compatible contract `llm/proxy_client.py` already implements
(POST /chat/completions, `stream: true` for SSE).

Backed by Hugging Face (Inference Providers' OpenAI-compatible router) as
the primary upstream, with Groq (https://groq.com) as a fallback tried
only if Hugging Face's request fails - see _upstreams(). Both are themselves
OpenAI-compatible, which makes this a thin **relay**, not a translator:
swap in the real API key(s), pin the model server-side per upstream (never
trust the caller's `model` field - the same "swappable without touching
application code" principle the rest of this codebase already applies to
the proxy boundary), forward the request, and for streaming responses pass
the upstream's SSE bytes straight through unchanged - they're already in
exactly the wire format `llm/proxy_client.py`'s `stream_complete()` parses.
No provider SDK dependency needed here either - plain `httpx`, already used
everywhere else in this codebase for outbound HTTP.

Run it: `uv run fastapi run src/ucenik/llm_proxy/main.py --port 4000`
(matches the default `LLM_PROXY_URL=http://localhost:4000` in .env.example).
"""

import logging

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ucenik.core.logging_config import configure_logging
from ucenik.llm_proxy.config import proxy_settings

# Same structured-JSON-to-Loki pipeline as the main app (core/logging_config.py)
# - called at import time (not inside a lifespan hook - this service has
# none) so it's in effect before the first request log line, and so its
# logs land in the same shape Promtail's JSON parsing stage expects (see
# observability/promtail-config.yaml).
configure_logging()

app = FastAPI(title="ucenik-llm-proxy")
logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0)


class _Upstream:
    def __init__(self, name: str, base_url: str, model: str, api_key: str) -> None:
        self.name = name
        self.url = f"{base_url}/chat/completions"
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _upstreams() -> list[_Upstream]:
    """Ordered list of upstreams to try, Hugging Face first, falling back to
    Groq if Hugging Face's request fails (network error or non-2xx status).
    Hugging Face is only included if HF_API_KEY is actually set - empty
    means it's skipped entirely and behavior is Groq-only (fail straight to
    an error on Groq's own failure, no fallback to try). Groq has no such
    gate - groq_api_key is the one credential this service assumes is
    always configured, so it's always present as the last resort.
    """
    upstreams = []
    if proxy_settings.hf_api_key:
        upstreams.append(
            _Upstream("huggingface", proxy_settings.hf_base_url, proxy_settings.hf_model, proxy_settings.hf_api_key)
        )
    upstreams.append(
        _Upstream("groq", proxy_settings.groq_base_url, proxy_settings.groq_model, proxy_settings.groq_api_key)
    )
    return upstreams


async def _require_shared_secret(authorization: str | None = Header(default=None)) -> None:
    if not proxy_settings.llm_proxy_api_key:
        return
    if authorization != f"Bearer {proxy_settings.llm_proxy_api_key}":
        raise HTTPException(status_code=401, detail="invalid or missing proxy API key")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/chat/completions", dependencies=[Depends(_require_shared_secret)])
async def chat_completions(request: Request):
    body = await request.json()
    stream = bool(body.get("stream"))

    if stream:
        return StreamingResponse(_relay_stream(body), media_type="text/event-stream")

    last_response = None
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for upstream in _upstreams():
            # Model selection is proxy-side - see module docstring. Whatever
            # the caller sent (e.g. LLM_PROXY_MODEL on the main app's side,
            # just an advisory label there) is overwritten per upstream.
            payload = {**body, "model": upstream.model}
            try:
                response = await client.post(upstream.url, json=payload, headers=upstream.headers)
            except httpx.HTTPError as exc:
                logger.error(
                    "llm_proxy.upstream_error",
                    extra={"event": "llm_proxy.upstream_error", "upstream": upstream.name, "error": str(exc)},
                )
                last_response = None
                continue

            if response.status_code < 400:
                return JSONResponse(status_code=response.status_code, content=response.json())

            logger.warning(
                "llm_proxy.upstream_non_2xx",
                extra={
                    "event": "llm_proxy.upstream_non_2xx",
                    "upstream": upstream.name,
                    "status": response.status_code,
                    "body": response.text[:500],
                },
            )
            last_response = response
            # try the next upstream, if any - this one failed

    if last_response is not None:
        return JSONResponse(status_code=last_response.status_code, content=last_response.json())
    raise HTTPException(status_code=503, detail="upstream LLM provider unreachable")


async def _relay_stream(body: dict):
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        last_status = None
        for upstream in _upstreams():
            payload = {**body, "model": upstream.model}
            committed = False
            try:
                async with client.stream("POST", upstream.url, json=payload, headers=upstream.headers) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        logger.warning(
                            "llm_proxy.upstream_non_2xx",
                            extra={
                                "event": "llm_proxy.upstream_non_2xx",
                                "upstream": upstream.name,
                                "status": response.status_code,
                            },
                        )
                        last_status = response.status_code
                        continue  # nothing yielded yet - safe to try the next upstream

                    # Status is good - committed to this upstream now. A
                    # failure from here on (mid-stream) can't fall back to
                    # another upstream without corrupting output that's
                    # already been sent to our own caller, so it isn't
                    # retried below; it just ends the response, same as
                    # this service's original (pre-fallback) behavior.
                    committed = True
                    # The upstream's SSE bytes are already the exact wire
                    # format llm/proxy_client.py's stream_complete() parses
                    # - passed through raw, never re-parsed/re-encoded.
                    async for chunk in response.aiter_raw():
                        yield chunk
                    return
            except httpx.HTTPError as exc:
                logger.error(
                    "llm_proxy.upstream_error",
                    extra={"event": "llm_proxy.upstream_error", "upstream": upstream.name, "error": str(exc)},
                )
                if committed:
                    yield 'data: {"error": {"message": "upstream connection lost"}}\n\n'
                    yield "data: [DONE]\n\n"
                    return
                last_status = None
                continue

        detail = f"upstream error {last_status}" if last_status else "upstream LLM provider unreachable"
        yield f'data: {{"error": {{"message": "{detail}"}}}}\n\n'
        yield "data: [DONE]\n\n"
