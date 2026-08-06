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


async def query_similar(subject_id: str, query_embedding: list[float], n_results: int = 5) -> dict:
    collection = await _get_collection(subject_id)
    return await collection.query(query_embeddings=[query_embedding], n_results=n_results)
