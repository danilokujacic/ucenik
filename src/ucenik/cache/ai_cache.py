"""Redis cache for embeddings - avoids re-embedding identical chunk text.

Pure efficiency, not correctness: mainly pays off re-ingesting a lightly
edited document, where most chunks are unchanged text and hit the cache.
Cache key includes the embedding model's own identity, not just a hash of
the text - swapping embedding models invalidates the cache automatically,
since old vectors would belong to a different (now-irrelevant) vector space.
"""

import hashlib
import json

from ucenik.core.config import settings
from ucenik.core.redis import get_redis

_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days - embeddings are deterministic, this just caps unbounded growth


def _cache_key(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"embedding:{settings.embedding_model}:{digest}"


async def get_cached_embedding(text: str) -> list[float] | None:
    raw = await get_redis().get(_cache_key(text))
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached_embedding(text: str, embedding: list[float]) -> None:
    await get_redis().set(_cache_key(text), json.dumps(embedding), ex=_TTL_SECONDS)
