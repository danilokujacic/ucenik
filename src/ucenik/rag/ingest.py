"""Ingest pipeline orchestrator - ties together extraction, chunking,
contextual enrichment, embedding, caching, and vector storage for one
uploaded document. Runs as a FastAPI BackgroundTask (see api/documents.py),
not inline in the upload request - see docs/rag-notes.md for why.
"""

import logging
from datetime import datetime, timezone

from ucenik.cache.ai_cache import get_cached_embedding, set_cached_embedding
from ucenik.core.storage import download_file
from ucenik.models.documents import Document, DocumentStatus
from ucenik.rag.chunker import chunk_text
from ucenik.rag.contextualizer import apply_context, generate_context
from ucenik.rag.embedder import embed_documents
from ucenik.rag.extractor import extract_text
from ucenik.rag.vector_store import delete_document_chunks, upsert_chunks

logger = logging.getLogger(__name__)


async def ingest_document(document_id: str) -> None:
    document = await Document.get(document_id)
    if document is None:
        logger.error("ingest_document: document %s not found", document_id)
        return

    document.status = DocumentStatus.PROCESSING
    document.updated_at = datetime.now(timezone.utc)
    await document.save()

    try:
        raw_bytes = await download_file(document.file_hash)
        text = extract_text(document.content_type, raw_bytes)

        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("chunking produced zero chunks")

        # Pass 1: cache lookup (keyed on the RAW chunk text, not the
        # contextualized one - a hit skips the LLM context call too, not
        # just the embedding call) + contextual enrichment for misses.
        final_texts: list[str | None] = [None] * len(chunks)
        embeddings: list[list[float] | None] = [None] * len(chunks)
        miss_indices: list[int] = []

        for i, chunk in enumerate(chunks):
            cached = await get_cached_embedding(chunk.text)
            if cached is not None:
                final_texts[i] = chunk.text
                embeddings[i] = cached
            else:
                context = await generate_context(text, chunk.text)
                final_texts[i] = apply_context(context, chunk.text)
                miss_indices.append(i)

        # Pass 2: batch-embed everything that missed the cache.
        if miss_indices:
            texts_to_embed = [final_texts[i] for i in miss_indices]
            fresh_embeddings = await embed_documents(texts_to_embed)
            for i, embedding in zip(miss_indices, fresh_embeddings):
                embeddings[i] = embedding
                await set_cached_embedding(chunks[i].text, embedding)

        chunk_ids = [f"{document.id}_{c.index}" for c in chunks]
        metadatas = [
            {
                "document_id": str(document.id),
                "chunk_index": c.index,
                "source_filename": document.filename,
            }
            for c in chunks
        ]

        # Delete old chunks first - re-ingest safety net: if the new version
        # has fewer chunks than the old one, upsert alone would leave stale
        # orphans searchable forever (see docs/rag-notes.md).
        await delete_document_chunks(document.subject_id, str(document.id))
        await upsert_chunks(document.subject_id, chunk_ids, embeddings, final_texts, metadatas)

        document.status = DocumentStatus.READY
        document.chunk_count = len(chunks)
        document.error = None
    except Exception as exc:
        logger.exception("ingest failed for document %s", document_id)
        document.status = DocumentStatus.FAILED
        document.error = str(exc)

    document.updated_at = datetime.now(timezone.utc)
    await document.save()
