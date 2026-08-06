"""Wraps the embedding model - text in, fixed-size vector out.

BGE-M3, run locally via sentence-transformers (self-hosted, no per-call cost
for something run on every chunk). SentenceTransformer.encode() is a blocking
CPU-bound call, so it's offloaded to a thread via asyncio.to_thread() to
avoid blocking the event loop.

embed_documents/embed_query are kept separate rather than one generic
embed_texts() a caller could misuse: some embedding models use different
prompts/prefixes for queries vs documents, and mixing them up doesn't error,
it just silently produces worse retrieval. BGE-M3 itself happens to use an
empty prefix for both (prompts={'query': '', 'document': ''}) - but passing
prompt_name explicitly still costs nothing and keeps this correct automatically
if that ever changes upstream.
"""

import asyncio

from sentence_transformers import SentenceTransformer

from ucenik.core.config import settings

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed chunk text for storage (ingest side)."""
    model = _get_model()
    vectors = await asyncio.to_thread(
        model.encode, texts, prompt_name="document", normalize_embeddings=True
    )
    return vectors.tolist()


async def embed_query(text: str) -> list[float]:
    """Embed a search query (retrieval side, Phase 5)."""
    model = _get_model()
    vectors = await asyncio.to_thread(
        model.encode, [text], prompt_name="query", normalize_embeddings=True
    )
    return vectors[0].tolist()
