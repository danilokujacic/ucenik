"""Redis cache for ingested chunks - avoids re-running the contextual blurb
LLM call and the embedding call for a chunk that was already processed.

Mainly pays off re-uploading a lightly edited document: that's a new
Document (dedup is by file hash, see services/documents.py) but most of its
chunks are unchanged text and hit the cache.

What's cached is the blurb *and* the embedding together. Caching only the
embedding (the previous design) meant a hit had no blurb to put back into
the stored chunk text - the vector had been computed from
breadcrumb + blurb + chunk, but the text stored next to it (what BM25 and
the Tutor read) silently became the bare chunk.

Key: subject + breadcrumb (which starts with the filename) + chunk text,
not the chunk text alone - identical text in two different documents (a
repeated header, worksheet instructions) has different surroundings and
needs its own blurb, rather than inheriting whichever document's got
cached first. The embedding model's identity is in the key too: swapping
models invalidates everything automatically, since old vectors would belong
to a different vector space. The "v2" prefix leaves old embedding-only
entries unread; they expire on their own TTL.

Deliberately not part of the key: the neighboring text the blurb was
generated with. If only a neighbor changed in an edited re-upload, this
chunk reuses its slightly older blurb - a fair trade for the cache still
hitting on the common case at all.
"""

import hashlib
import json
from dataclasses import dataclass

from ucenik.core.config import settings
from ucenik.core.redis import get_redis

_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days - just caps unbounded growth


@dataclass
class CachedChunk:
    context: str
    embedding: list[float]


def _cache_key(subject_id: str, location: str, chunk_text: str) -> str:
    material = json.dumps([subject_id, location, chunk_text])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"chunk:v2:{settings.embedding_model}:{digest}"


async def get_cached_chunk(subject_id: str, location: str, chunk_text: str) -> CachedChunk | None:
    raw = await get_redis().get(_cache_key(subject_id, location, chunk_text))
    if raw is None:
        return None
    value = json.loads(raw)
    return CachedChunk(context=value["context"], embedding=value["embedding"])


async def set_cached_chunk(subject_id: str, location: str, chunk_text: str, entry: CachedChunk) -> None:
    value = json.dumps({"context": entry.context, "embedding": entry.embedding})
    await get_redis().set(_cache_key(subject_id, location, chunk_text), value, ex=_TTL_SECONDS)
