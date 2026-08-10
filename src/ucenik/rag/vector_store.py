"""Chroma wrapper - one collection per subject, upsert/query/delete.

Collection-per-subject means retrieval is structurally scoped: a query
against one subject's collection cannot return another subject's chunks, no
manual filtering required (see docs/rag-notes.md).
"""

import chromadb
from chromadb.api.async_client import AsyncClient

from ucenik.core.config import settings

_client: AsyncClient | None = None


async def _get_client() -> AsyncClient:
    global _client
    if _client is None:
        _client = await chromadb.AsyncHttpClient(host=settings.chroma_host, port=settings.chroma_port)
    return _client


def _collection_name(subject_id: str) -> str:
    return f"subject_{subject_id}"


async def _get_collection(subject_id: str):
    client = await _get_client()
    return await client.get_or_create_collection(
        name=_collection_name(subject_id),
        metadata={"hnsw:space": "cosine"},
    )


async def upsert_chunks(
    subject_id: str,
    chunk_ids: list[str],
    embeddings: list[list[float]],
    texts: list[str],
    metadatas: list[dict],
) -> None:
    collection = await _get_collection(subject_id)
    await collection.upsert(ids=chunk_ids, embeddings=embeddings, documents=texts, metadatas=metadatas)


async def delete_document_chunks(subject_id: str, document_id: str) -> None:
    """Delete every chunk belonging to `document_id` - call before
    re-ingesting an updated document, so a shrinking chunk count can't leave
    stale orphans searchable forever (see docs/rag-notes.md).
    """
    collection = await _get_collection(subject_id)
    await collection.delete(where={"document_id": document_id})


async def delete_subject_collection(subject_id: str) -> None:
    """Drop this subject's entire collection in one call - call when the
    subject itself is deleted, so its chunks don't outlive it (see
    api/subjects.py's delete_subject). Cheaper and more thorough than
    deleting document-by-document.
    """
    client = await _get_client()
    try:
        await client.delete_collection(name=_collection_name(subject_id))
    except chromadb.errors.NotFoundError:
        # No collection was ever created for this subject - e.g. it never
        # had a document finish ingesting. Nothing to clean up.
        pass


async def query_similar(subject_id: str, query_embedding: list[float], n_results: int = 5) -> dict:
    collection = await _get_collection(subject_id)
    return await collection.query(query_embeddings=[query_embedding], n_results=n_results)


async def get_all_chunks(subject_id: str) -> list[dict]:
    """Every chunk in a subject's collection - `[{id, text, metadata}, ...]`.

    Used by rag/retriever.py's BM25 side of hybrid search: BM25 needs the
    whole corpus to score against (unlike the dense side, which only needs
    the query vector - Chroma's index does the narrowing there). Fine at the
    per-subject scale this runs at; would need a real search index instead
    of an in-memory BM25 pass if a single subject's document count grew
    large enough for this to become the bottleneck.
    """
    collection = await _get_collection(subject_id)
    result = await collection.get(include=["documents", "metadatas"])
    return [
        {"id": chunk_id, "text": text, "metadata": metadata}
        for chunk_id, text, metadata in zip(result["ids"], result["documents"], result["metadatas"])
    ]
