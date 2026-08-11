"""Tests for src/ucenik/embedding_service/ - the self-hosted embedding
service itself, separate from the main app (tests/conftest.py's `client`
fixture is not this app). A fake model object stands in for the
module-level `_model` global, so these stay fast and dependency-free (no
~2.3GB of real weights to load, mirroring tests/test_llm_proxy.py's same
reasoning for not making real upstream calls). Real embedding correctness
(does BGE-M3 actually produce good vectors) is verified elsewhere -
tests/test_documents.py calls embed_query() for real, which after this
service's refactor means genuinely hitting a running instance of this
service over HTTP - that's the right place for "does this actually work",
not here.
"""

from unittest.mock import patch

import numpy as np
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ucenik.embedding_service import main
from ucenik.embedding_service.config import embedding_service_settings


class _FakeModel:
    """Stands in for SentenceTransformer - real .encode() returns a numpy
    array (hence np.array here, not a plain list: main.py calls .tolist()
    on whatever comes back, same as the real thing)."""

    def __init__(self, dim: int = 4):
        self.dim = dim
        self.last_call: dict | None = None

    def encode(self, texts, prompt_name=None, normalize_embeddings=None):
        self.last_call = {"texts": texts, "prompt_name": prompt_name, "normalize_embeddings": normalize_embeddings}
        return np.array([[float(i)] * self.dim for i in range(len(texts))])


@pytest_asyncio.fixture
async def service_client():
    fake_model = _FakeModel()
    with patch.object(main, "_model", fake_model):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, fake_model


async def test_health_reports_model_loaded(service_client):
    client, _ = service_client
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_loaded": True}


async def test_health_reports_not_loaded_when_model_is_none():
    with patch.object(main, "_model", None):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.get("/health")
    assert response.json() == {"status": "ok", "model_loaded": False}


async def test_embed_returns_vectors_and_calls_encode_correctly(service_client):
    client, fake_model = service_client
    response = await client.post("/embed", json={"texts": ["hello", "world"], "prompt_name": "document"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["embeddings"]) == 2
    assert body["embeddings"][0] == [0.0, 0.0, 0.0, 0.0]
    assert body["embeddings"][1] == [1.0, 1.0, 1.0, 1.0]
    assert fake_model.last_call == {
        "texts": ["hello", "world"],
        "prompt_name": "document",
        "normalize_embeddings": True,
    }


async def test_embed_passes_query_prompt_name_through(service_client):
    """The whole reason prompt_name is explicit, not inferred - see
    rag/embedder.py's docstring: mixing query/document prompts doesn't
    error, it just silently produces worse retrieval.
    """
    client, fake_model = service_client
    response = await client.post("/embed", json={"texts": ["a question"], "prompt_name": "query"})

    assert response.status_code == 200
    assert fake_model.last_call["prompt_name"] == "query"


async def test_embed_rejects_invalid_prompt_name(service_client):
    client, _ = service_client
    response = await client.post("/embed", json={"texts": ["x"], "prompt_name": "bogus"})
    assert response.status_code == 422


async def test_embed_returns_503_when_model_not_loaded():
    with patch.object(main, "_model", None):
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            response = await c.post("/embed", json={"texts": ["x"], "prompt_name": "document"})
    assert response.status_code == 503


async def test_auth_open_when_shared_secret_unset(service_client):
    """Default config (embedding_service_api_key empty) - no Authorization
    header required, matching llm_proxy's own behavior."""
    client, _ = service_client
    response = await client.post("/embed", json={"texts": ["x"], "prompt_name": "document"})
    assert response.status_code == 200


async def test_auth_required_when_shared_secret_set(service_client):
    client, _ = service_client
    with patch.object(embedding_service_settings, "embedding_service_api_key", "shh-secret"):
        unauthorized = await client.post("/embed", json={"texts": ["x"], "prompt_name": "document"})
        assert unauthorized.status_code == 401

        ok = await client.post(
            "/embed",
            json={"texts": ["x"], "prompt_name": "document"},
            headers={"Authorization": "Bearer shh-secret"},
        )
    assert ok.status_code == 200
