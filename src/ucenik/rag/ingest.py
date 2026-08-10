"""Ingest pipeline orchestrator - ties together extraction, chunking,
contextual enrichment, embedding, caching, and vector storage for one
uploaded document. Runs as a FastAPI BackgroundTask (see api/documents.py),
not inline in the upload request - see docs/rag-notes.md for why.
"""

import logging
import time
from datetime import UTC, datetime

from ucenik.cache.ai_cache import get_cached_embedding, set_cached_embedding
from ucenik.cache.chat_cache import bump_subject_version
from ucenik.core.quota import check_quota, record_usage
from ucenik.core.storage import download_file
from ucenik.errors.user_messages import safe_job_error_message
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
    document.updated_at = datetime.now(UTC)
    await document.save()

    log_context = {
        "document_id": str(document.id),
        "subject_id": document.subject_id,
        "user_id": document.uploaded_by,
    }
    logger.info("ingest.started", extra={"event": "ingest.started", **log_context})
    start = time.perf_counter()

    try:
        raw_bytes = await download_file(document.file_hash)
        text = await extract_text(document.content_type, raw_bytes)

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
                continue

            await check_quota(document.uploaded_by)
            result = await generate_context(text, chunk.text)
            await record_usage(document.uploaded_by, result.total_tokens)

            final_texts[i] = apply_context(result.content, chunk.text)
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

        # What's retrievable for this subject just changed - invalidate any
        # cached Tutor answers (cache/chat_cache.py) rather than let them
        # keep serving pre-update material.
        await bump_subject_version(document.subject_id)

        document.status = DocumentStatus.READY
        document.chunk_count = len(chunks)
        document.error = None

        logger.info(
            "ingest.completed",
            extra={
                "event": "ingest.completed",
                **log_context,
                "chunk_count": len(chunks),
                "cache_hits": len(chunks) - len(miss_indices),
                "cache_misses": len(miss_indices),
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
    except Exception as exc:
        # Full detail goes to the logs (str(exc) here, real internals like
        # "failed to reach the LLM proxy" or "OCR support not yet
        # implemented") - only the sanitized version is stored on the
        # document, since that field is read straight back through a plain
        # GET with no request/response cycle left to redact it at.
        logger.exception("ingest.failed", extra={"event": "ingest.failed", **log_context, "error": str(exc)})
        document.status = DocumentStatus.FAILED
        document.error = safe_job_error_message(exc)

    document.updated_at = datetime.now(UTC)
    await document.save()
