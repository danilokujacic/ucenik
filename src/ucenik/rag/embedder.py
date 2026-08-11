"""Client for the self-hosted embedding service (src/ucenik/embedding_service/)
- text in, fixed-size vector out, over HTTP rather than loading the model
in this process directly. See that service's module docstring for the full
reasoning; short version: `app` and the Celery `worker` are separate
processes, and each loading BGE-M3 independently would double the RAM/CPU
cost for two identical copies of the same weights - one process (the
embedding service) owns the model, everyone else calls it, mirroring how
llm/proxy_client.py relates to llm_proxy.

embed_documents/embed_query are kept separate rather than one generic
embed_texts() a caller could misuse: some embedding models use different
prompts/prefixes for queries vs documents, and mixing them up doesn't error,
it just silently produces worse retrieval. BGE-M3 itself happens to use an
empty prefix for both (prompts={'query': '', 'document': ''}) - but passing
prompt_name explicitly still costs nothing and keeps this correct automatically
if that ever changes upstream.
"""

import httpx

from ucenik.core.config import settings


class EmbeddingServiceError(Exception):
    """Raised when the embedding service is unreachable or errors - mirrors
    llm/proxy_client.py's LLMProxyError shape (a clean, app-specific
    exception instead of a raw httpx one leaking to callers)."""


def _auth_headers() -> dict[str, str]:
    if not settings.embedding_service_api_key:
        return {}
    return {"Authorization": f"Bearer {settings.embedding_service_api_key}"}


async def _embed(texts: list[str], prompt_name: str) -> list[list[float]]:
    async with httpx.AsyncClient(
        base_url=settings.embedding_service_url,
        timeout=settings.embedding_service_timeout_seconds,
    ) as client:
        try:
            response = await client.post(
                "/embed", json={"texts": texts, "prompt_name": prompt_name}, headers=_auth_headers()
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingServiceError("failed to reach the embedding service") from exc
        return response.json()["embeddings"]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed chunk text for storage (ingest side)."""
    return await _embed(texts, "document")


async def embed_query(text: str) -> list[float]:
    """Embed a search query (retrieval side, Phase 5)."""
    embeddings = await _embed([text], "query")
    return embeddings[0]
