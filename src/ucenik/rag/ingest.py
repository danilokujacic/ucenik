"""Ingest pipeline orchestrator - ties together structured extraction,
per-section chunking, breadcrumbs + contextual enrichment, embedding,
caching, and vector storage for one uploaded document. Runs as a FastAPI
BackgroundTask (see api/documents.py),
not inline in the upload request - see docs/rag-notes.md for why.
"""

import logging
import time
from datetime import UTC, datetime

from ucenik.cache.ai_cache import CachedChunk, get_cached_chunk, set_cached_chunk
from ucenik.cache.chat_cache import bump_subject_version
from ucenik.core.quota import check_quota, record_usage
from ucenik.core.storage import download_file
from ucenik.errors.user_messages import safe_job_error_message
from ucenik.models.documents import Document, DocumentStatus
from ucenik.rag.chunker import breadcrumb, chunk_sections
from ucenik.rag.contextualizer import apply_context, generate_context
from ucenik.rag.embedder import embed_documents
from ucenik.rag.extractor import extract_sections, render_sections
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
        sections = await extract_sections(document.content_type, raw_bytes)
        document_text = render_sections(sections)

        chunks = chunk_sections(sections)
        if not chunks:
            raise ValueError("chunking produced zero chunks")

        # Free context first: every chunk's heading path, e.g.
        # "photosynthesis.pdf > Chapter 3 > The Calvin cycle".
        locations = [breadcrumb(document.filename, c.heading_path) for c in chunks]

        # Pass 1: cache lookup (a hit restores both the blurb and the
        # embedding - skips the LLM context call AND the embedding call) +
        # contextual enrichment for misses, shown the text around the chunk.
        contexts: list[str] = [""] * len(chunks)
        embeddings: list[list[float] | None] = [None] * len(chunks)
        miss_indices: list[int] = []

        for i, chunk in enumerate(chunks):
            cached = await get_cached_chunk(document.subject_id, locations[i], chunk.text)
            if cached is not None:
                contexts[i] = cached.context
                embeddings[i] = cached.embedding
                continue

            await check_quota(document.uploaded_by)
            result = await generate_context(
                document_text,
                locations[i],
                chunk.text,
                text_before=chunks[i - 1].raw_text if i > 0 else "",
                text_after=chunks[i + 1].raw_text if i + 1 < len(chunks) else "",
            )
            await record_usage(document.uploaded_by, result.total_tokens)

            contexts[i] = result.content.strip()
            miss_indices.append(i)

        # Identical for hits and misses: breadcrumb + blurb + chunk - what
        # gets embedded is exactly what gets stored (BM25 + the Tutor read it).
        final_texts = [apply_context(locations[i], contexts[i], c.text) for i, c in enumerate(chunks)]

        # Pass 2: batch-embed everything that missed the cache.
        if miss_indices:
            fresh_embeddings = await embed_documents([final_texts[i] for i in miss_indices])
            for i, embedding in zip(miss_indices, fresh_embeddings, strict=True):
                embeddings[i] = embedding
                await set_cached_chunk(
                    document.subject_id,
                    locations[i],
                    chunks[i].text,
                    CachedChunk(context=contexts[i], embedding=embedding),
                )

        chunk_ids = [f"{document.id}_{c.index}" for c in chunks]
        # breadcrumb + raw_text are for rag/retriever.py's neighbor expansion:
        # stitching a hit and the chunks around it into one clean passage.
        metadatas = [
            {
                "document_id": str(document.id),
                "chunk_index": c.index,
                "source_filename": document.filename,
                "breadcrumb": locations[i],
                "raw_text": c.raw_text,
            }
            for i, c in enumerate(chunks)
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
