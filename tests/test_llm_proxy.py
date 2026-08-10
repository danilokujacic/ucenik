"""Tests for src/ucenik/llm_proxy/ - the self-hosted proxy service itself,
separate from the main app (tests/conftest.py's `client` fixture is not
this app). No real Groq calls here - a hand-rolled fake stands in for
httpx.AsyncClient at the two outbound-call sites in llm_proxy/main.py, so
these stay fast and dependency-free. The real wire-level behavior (actual
SSE bytes over actual HTTP) is verified live and separately - see this
session's notes in docs/rag-notes.md; that's not something to re-run on
every test invocation.
"""

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ucenik.llm_proxy.config import proxy_settings


@pytest.fixture(autouse=True)
def _no_hf_fallback_by_default():
    """Every test in this file except the ones under "Hugging Face
    fallback" below assumes Groq is the only upstream. Patching this here,
    for every test, rather than trusting the ambient default to be empty -
    a real .env with a real HF_API_KEY filled in (as local dev's does once
    the fallback is actually configured) would otherwise silently turn
    every single-upstream test in this file into an unintended two-upstream
    one, without any of them necessarily failing loudly (most only assert
    on the final response, not on how many calls it took to get there).
    Tests that specifically want the fallback active patch hf_api_key back
    to a real value themselves.
    """
    with patch.object(proxy_settings, "hf_api_key", ""):
        yield


@pytest_asyncio.fixture
async def proxy_client():
    from ucenik.llm_proxy.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text_data=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text_data

    def json(self):
        return self._json_data


class _FakeStreamResponse:
    def __init__(self, status_code=200, raw_chunks=None):
        self.status_code = status_code
        self._raw_chunks = raw_chunks or []

    async def aiter_raw(self):
        for chunk in self._raw_chunks:
            yield chunk

    async def aread(self):
        return b""


class _StreamContextManager:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


def _fake_httpx_client(
    box: dict,
    *,
    post_response=None,
    post_exception=None,
    post_responses: list | None = None,
    stream_response=None,
    stream_exception=None,
    stream_responses: list | None = None,
):
    """Returns a class standing in for httpx.AsyncClient - `box["instance"]`
    captures the created instance so tests can assert on what it was asked
    to send, after the fact.

    `post_response`/`post_exception` (and their `stream_*` counterparts)
    cover the single-upstream case: every call gets the same canned result.
    `post_responses`/`stream_responses` cover the fallback case: a list of
    `(response_or_None, exception_or_None)` pairs, one per call in order -
    call N of the list drives the Nth request the code under test makes
    (e.g. Groq first, Hugging Face second).
    """

    class _Client:
        def __init__(self, *args, **kwargs):
            self.captured_post = None
            self.captured_stream = None
            self.captured_posts: list[dict] = []
            self.captured_streams: list[dict] = []
            box["instance"] = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            call = {"url": url, "json": json, "headers": headers}
            self.captured_post = call
            self.captured_posts.append(call)
            if post_responses is not None:
                response, exception = post_responses[len(self.captured_posts) - 1]
                if exception:
                    raise exception
                return response
            if post_exception:
                raise post_exception
            return post_response

        def stream(self, method, url, json=None, headers=None):
            call = {"method": method, "url": url, "json": json, "headers": headers}
            self.captured_stream = call
            self.captured_streams.append(call)
            if stream_responses is not None:
                response, exception = stream_responses[len(self.captured_streams) - 1]
                if exception:
                    raise exception
                return _StreamContextManager(response)
            if stream_exception:
                raise stream_exception
            return _StreamContextManager(stream_response)

    return _Client


async def test_health(proxy_client):
    response = await proxy_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_auth_open_when_shared_secret_unset(proxy_client):
    """Default config (LLM_PROXY_API_KEY empty) - no Authorization header
    required, matching llm/proxy_client.py's own behavior of omitting the
    header when its own key is empty.
    """
    box = {}
    fake = _fake_httpx_client(box, post_response=_FakeResponse(200, {"choices": []}))
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post("/chat/completions", json={"model": "x", "messages": []})
    assert response.status_code == 200


async def test_auth_required_when_shared_secret_set(proxy_client):
    with patch.object(proxy_settings, "llm_proxy_api_key", "shh-secret"):
        response = await proxy_client.post("/chat/completions", json={"model": "x", "messages": []})
        assert response.status_code == 401

        box = {}
        fake = _fake_httpx_client(box, post_response=_FakeResponse(200, {"choices": []}))
        with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
            ok = await proxy_client.post(
                "/chat/completions",
                json={"model": "x", "messages": []},
                headers={"Authorization": "Bearer shh-secret"},
            )
        assert ok.status_code == 200


async def test_model_is_always_overridden_server_side(proxy_client):
    """The caller's `model` field is accepted but never trusted - the proxy
    always substitutes its own configured GROQ_MODEL, per main.py's module
    docstring on why (swappable behind the proxy without touching app code).
    """
    box = {}
    fake = _fake_httpx_client(box, post_response=_FakeResponse(200, {"choices": [{"message": {"content": "hi"}}]}))
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post(
            "/chat/completions", json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
        )

    assert response.status_code == 200
    sent_body = box["instance"].captured_post["json"]
    assert sent_body["model"] == proxy_settings.groq_model
    assert sent_body["model"] != "gpt-4o-mini"


async def test_non_streaming_response_is_relayed_through(proxy_client):
    upstream_body = {
        "id": "chatcmpl-abc",
        "choices": [{"message": {"role": "assistant", "content": "The answer is 4."}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    box = {}
    fake = _fake_httpx_client(box, post_response=_FakeResponse(200, upstream_body))
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post(
            "/chat/completions", json={"model": "x", "messages": [{"role": "user", "content": "2+2?"}]}
        )

    assert response.status_code == 200
    assert response.json() == upstream_body


async def test_upstream_error_status_is_relayed(proxy_client):
    box = {}
    fake = _fake_httpx_client(
        box, post_response=_FakeResponse(401, {"error": {"message": "invalid Groq API key"}}, text_data="{}")
    )
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post("/chat/completions", json={"model": "x", "messages": []})

    assert response.status_code == 401


async def test_upstream_unreachable_returns_503(proxy_client):
    import httpx

    box = {}
    fake = _fake_httpx_client(box, post_exception=httpx.ConnectError("connection refused"))
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post("/chat/completions", json={"model": "x", "messages": []})

    assert response.status_code == 503


async def test_streaming_bytes_are_relayed_raw_and_model_overridden(proxy_client):
    raw_chunks = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n\n',
        b"data: [DONE]\n\n",
    ]
    box = {}
    fake = _fake_httpx_client(box, stream_response=_FakeStreamResponse(200, raw_chunks))
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post(
            "/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )

    assert response.status_code == 200
    body = response.text
    assert body == "".join(chunk.decode() for chunk in raw_chunks)
    assert box["instance"].captured_stream["json"]["model"] == proxy_settings.groq_model


async def test_streaming_upstream_failure_yields_error_event_not_a_crash(proxy_client):
    import httpx

    box = {}
    fake = _fake_httpx_client(box, stream_exception=httpx.ConnectError("connection refused"))
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post(
            "/chat/completions",
            json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )

    assert response.status_code == 200  # headers already sent by the time the failure surfaces
    assert "error" in response.text
    assert response.text.strip().endswith("data: [DONE]")


# --- Fallback to Groq when Hugging Face fails ---
# Hugging Face disabled by default (hf_api_key == "" in test settings, same
# as real local dev with nothing filled in) - the tests above all exercise
# exactly one upstream (Groq, the only one left once HF is skipped) and
# stay valid unchanged. These patch hf_api_key on to actually exercise the
# two-upstream path: Hugging Face first, falling back to Groq.


async def test_no_fallback_attempted_when_hf_not_configured(proxy_client):
    """Explicit regression guard for the opt-in behavior: with hf_api_key
    unset (the autouse fixture above), a Groq failure must not trigger a
    second call.
    """
    box = {}
    fake = _fake_httpx_client(box, post_response=_FakeResponse(500, {"error": "groq down"}, text_data="{}"))
    with patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake):
        response = await proxy_client.post("/chat/completions", json={"model": "x", "messages": []})

    assert response.status_code == 500
    assert len(box["instance"].captured_posts) == 1


async def test_falls_back_to_groq_when_huggingface_fails_non_streaming(proxy_client):
    box = {}
    fake = _fake_httpx_client(
        box,
        post_responses=[
            (_FakeResponse(500, {"error": "hf down"}, text_data="{}"), None),
            (_FakeResponse(200, {"choices": [{"message": {"content": "from Groq"}}]}), None),
        ],
    )
    with (
        patch.object(proxy_settings, "hf_api_key", "hf_test_key"),
        patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake),
    ):
        response = await proxy_client.post(
            "/chat/completions", json={"model": "x", "messages": [{"role": "user", "content": "hi"}]}
        )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "from Groq"

    calls = box["instance"].captured_posts
    assert len(calls) == 2
    assert calls[0]["json"]["model"] == proxy_settings.hf_model
    assert calls[1]["json"]["model"] == proxy_settings.groq_model
    assert calls[1]["url"] == f"{proxy_settings.groq_base_url}/chat/completions"


async def test_falls_back_to_groq_when_huggingface_unreachable_non_streaming(proxy_client):
    import httpx

    box = {}
    fake = _fake_httpx_client(
        box,
        post_responses=[
            (None, httpx.ConnectError("connection refused")),
            (_FakeResponse(200, {"choices": [{"message": {"content": "from Groq"}}]}), None),
        ],
    )
    with (
        patch.object(proxy_settings, "hf_api_key", "hf_test_key"),
        patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake),
    ):
        response = await proxy_client.post("/chat/completions", json={"model": "x", "messages": []})

    assert response.status_code == 200
    assert len(box["instance"].captured_posts) == 2


async def test_both_upstreams_failing_returns_last_error(proxy_client):
    box = {}
    fake = _fake_httpx_client(
        box,
        post_responses=[
            (_FakeResponse(500, {"error": "hf down"}, text_data="{}"), None),
            (_FakeResponse(503, {"error": "groq down"}, text_data="{}"), None),
        ],
    )
    with (
        patch.object(proxy_settings, "hf_api_key", "hf_test_key"),
        patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake),
    ):
        response = await proxy_client.post("/chat/completions", json={"model": "x", "messages": []})

    assert response.status_code == 503  # Groq's status - the last one tried
    assert len(box["instance"].captured_posts) == 2


async def test_falls_back_to_groq_when_huggingface_fails_streaming(proxy_client):
    raw_chunks = [
        b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]
    box = {}
    fake = _fake_httpx_client(
        box,
        stream_responses=[
            (_FakeStreamResponse(500, []), None),
            (_FakeStreamResponse(200, raw_chunks), None),
        ],
    )
    with (
        patch.object(proxy_settings, "hf_api_key", "hf_test_key"),
        patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake),
    ):
        response = await proxy_client.post(
            "/chat/completions",
            json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )

    assert response.status_code == 200
    assert response.text == "".join(chunk.decode() for chunk in raw_chunks)

    calls = box["instance"].captured_streams
    assert len(calls) == 2
    assert calls[0]["json"]["model"] == proxy_settings.hf_model
    assert calls[1]["json"]["model"] == proxy_settings.groq_model


async def test_mid_stream_failure_does_not_fall_back(proxy_client):
    """Once a response has actually started streaming bytes back to our own
    caller, switching upstream would corrupt already-sent output - a
    mid-stream failure ends the response instead of retrying.
    """
    import httpx

    class _BreaksMidStream(_FakeStreamResponse):
        async def aiter_raw(self):
            yield b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
            raise httpx.ReadError("connection dropped mid-stream")

    box = {}
    fake = _fake_httpx_client(box, stream_response=_BreaksMidStream(200))
    with (
        patch.object(proxy_settings, "hf_api_key", "hf_test_key"),
        patch("ucenik.llm_proxy.main.httpx.AsyncClient", fake),
    ):
        response = await proxy_client.post(
            "/chat/completions",
            json={"model": "x", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )

    assert len(box["instance"].captured_streams) == 1  # no fallback attempted
    assert "Hi" in response.text
    assert "upstream connection lost" in response.text
