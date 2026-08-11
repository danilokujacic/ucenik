"""Explains and logs, step by step, exactly what happens during the two
core RAG activities in this codebase - see docs/rag-notes.md for the
design and docs/session-qa-notes.md for the concept walkthrough this tool
puts into motion against real data.

Calls the SAME functions the real app uses (rag/extractor.py, chunker.py,
contextualizer.py, embedder.py, vector_store.py, retriever.py's own
internals, generator.py) - nothing here is reimplemented or simulated, so
what you see is exactly what the app itself does, just narrated out loud.

Two deliberate simplifications vs. the real orchestrators
(rag/ingest.py's ingest_document, services/chat.py's ask_question flow),
so this stays a standalone debug tool with no user/session/document
context required:
  - No quota enforcement (check_quota/record_usage) - there's no real user
    behind a CLI trace run.
  - No embedding cache (cache/ai_cache.py) - every run does fresh work, so
    what you see is never a stale cache hit from a previous run.
Everything else - chunking, contextualization, embedding, BM25, dense
search, RRF fusion, prompt construction - is the real thing.

Usage:
    uv run python scripts/rag_explain.py ingest path/to/document.pdf
    uv run python scripts/rag_explain.py ingest path/to/document.pdf --subject-id SUBJECT_ID --with-context
    uv run python scripts/rag_explain.py query SUBJECT_ID "question text"
    uv run python scripts/rag_explain.py query SUBJECT_ID "question text" --json-log /tmp/rag-trace.jsonl
    uv run python scripts/rag_explain.py demo path/to/document.pdf "question text"

`ingest` needs no running infra beyond the local embedding model (loads on
first use, ~2.3GB) unless --subject-id is passed (then Chroma too, from
docker-compose.yaml) or --with-context is passed (then the LLM proxy too -
`make llm-proxy`, see llm_proxy/main.py). `query` needs a subject that
already has ingested chunks in Chroma - either from `ingest --subject-id`
above, or a real subject from the actual running app.

`demo` is the fully self-contained path: spins up its own throwaway Chroma
container via testcontainers (same one tests/conftest.py uses for Mongo/
Redis - see that file), ingests the given document into it, then queries
it - both trace_ingest and trace_query end to end, against each other, in
one process, then tears the container down. Needs nothing pre-running
except Docker itself (testcontainers talks to the Docker daemon directly -
it isn't a Docker replacement, see docs/session-qa-notes.md's testcontainers
discussion if this errors with a connection-refused talking to Docker).

--json-log writes the same structured JSON-lines format core/logging_config.py
uses for the real app (one JSON object per line, Promtail/Loki-compatible) -
point it at a file if you want genuine queryable telemetry out of a trace
run, not just console narration.
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path

# testcontainers normally starts its own "Reaper" (Ryuk) container as a
# safety net - it bind-mounts the Docker socket into itself so it can clean
# up containers if this process dies abnormally (a plain `with` block's
# __exit__, which trace_demo does rely on, only covers *normal*
# termination). Docker Desktop's file-sharing restrictions reject that
# exact bind mount on some setups (verified: "Mounts denied: .../docker.sock
# is not shared from the host"), so Ryuk can never actually start there -
# disabling it is the documented workaround, not a hack. Must be set before
# testcontainers is imported below - it's read at import/first-use time.
# Trade-off accepted: a hard crash mid-run could leak a container - `docker
# rm -f` it by hand if that ever happens; Ctrl-C/normal exit still cleans up
# fine via `demo`'s `with ChromaContainer(...)` block.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from testcontainers.chroma import ChromaContainer

from ucenik.core.config import settings
from ucenik.core.logging_config import JSONFormatter
from ucenik.rag.chunker import chunk_text
from ucenik.rag.contextualizer import apply_context, generate_context
from ucenik.rag.embedder import embed_documents, embed_query
from ucenik.rag.extractor import _DOCX_CONTENT_TYPE, _PPTX_CONTENT_TYPE, _XLSX_CONTENT_TYPE, extract_text
from ucenik.rag.generator import build_messages
from ucenik.rag.retriever import _CANDIDATE_POOL_SIZE, _RRF_K, RetrievedChunk, _tokenize
from ucenik.rag.vector_store import get_all_chunks, query_similar, upsert_chunks

logger = logging.getLogger("rag_explain")

_CONTENT_TYPE_BY_SUFFIX = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": _DOCX_CONTENT_TYPE,
    ".pptx": _PPTX_CONTENT_TYPE,
    ".xlsx": _XLSX_CONTENT_TYPE,
}


def _guess_content_type(path: Path) -> str:
    content_type = _CONTENT_TYPE_BY_SUFFIX.get(path.suffix.lower())
    if content_type is None:
        raise SystemExit(
            f"Unsupported file type {path.suffix!r} - supported: {', '.join(sorted(_CONTENT_TYPE_BY_SUFFIX))}"
        )
    return content_type


def _setup_logging(json_log_path: str | None) -> None:
    """Console narration below is plain print() - readable while it's
    running, not a log format. This only wires up the *parallel* structured
    stream: same JSON-lines shape the real app emits, so --json-log
    produces genuine telemetry, not a toy.
    """
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if json_log_path:
        handler = logging.FileHandler(json_log_path)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        print(f"(structured JSON log events also being written to {json_log_path})")


def _step(title: str) -> None:
    print(f"\n{'-' * 70}\n>> {title}\n{'-' * 70}")


def _explain(text: str) -> None:
    print(f"   {text}")


def _log(event: str, **fields) -> None:
    logger.info(event, extra={"event": event, **fields})


def _preview(text: str, n: int = 90) -> str:
    flat = text.replace("\n", " ")
    return flat[:n] + ("..." if len(flat) > n else "")


# ---------------------------------------------------------------------------
# 1. Ingest trace: extract -> chunk -> (contextualize) -> embed -> store
# ---------------------------------------------------------------------------


async def trace_ingest(path: Path, raw_bytes: bytes, subject_id: str | None, with_context: bool) -> None:
    content_type = _guess_content_type(path)

    print(f"\n{'=' * 70}\nINGEST TRACE - {path.name} ({len(raw_bytes)} bytes, {content_type})\n{'=' * 70}")
    _log("rag_explain.ingest_started", file=path.name, content_type=content_type, byte_count=len(raw_bytes))

    # --- 1. Extraction ---
    _step("1. Extraction (rag/extractor.py)")
    _explain("Converting the raw file bytes into plain text. Format-dependent - PDF")
    _explain("goes page-by-page via pypdf, falling back to OCR per-page if a page has")
    _explain("no native text layer; .docx/.pptx/.xlsx each have their own path.")
    text = await extract_text(content_type, raw_bytes)
    _explain(f"-> Extracted {len(text)} characters.")
    _explain(f"-> Preview: {_preview(text, 200)!r}")
    _log("rag_explain.extracted", char_count=len(text))

    # --- 2. Chunking ---
    _step("2. Chunking (rag/chunker.py)")
    _explain("Splitting into overlapping, boundary-aware chunks - prefers paragraph")
    _explain("breaks, falling back to sentence/clause/word boundaries, hard character")
    _explain("cuts only as an absolute last resort. Sized in TOKENS (the embedding")
    _explain("model's own tokenizer), not characters - see docs/tokenizer-notes.md.")
    chunks = chunk_text(text)
    if not chunks:
        raise SystemExit("chunking produced zero chunks - nothing further to trace")
    _explain(f"-> Produced {len(chunks)} chunks.")
    for c in chunks[:3]:
        _explain(f"   chunk[{c.index}] ({len(c.text)} chars): {_preview(c.text)!r}")
    if len(chunks) > 3:
        _explain(f"   ... and {len(chunks) - 3} more")
    _log("rag_explain.chunked", chunk_count=len(chunks), chunk_char_lengths=[len(c.text) for c in chunks])

    # --- 3. Contextual enrichment (optional - real LLM calls) ---
    final_texts = [c.text for c in chunks]
    if with_context:
        _step("3. Contextual enrichment (rag/contextualizer.py) - REAL LLM CALLS")
        _explain("For each chunk, an LLM generates a 1-2 sentence blurb situating it")
        _explain("within the whole document, prepended before embedding - a chunk like")
        _explain("'it grew 3% that quarter' is meaningless alone; the blurb anchors it.")
        final_texts = []
        for c in chunks:
            result = await generate_context(text, c.text)
            enriched = apply_context(result.content, c.text)
            final_texts.append(enriched)
            _explain(f"   chunk[{c.index}] blurb: {result.content!r}  ({result.total_tokens} tokens)")
            _log("rag_explain.contextualized", chunk_index=c.index, blurb=result.content, tokens=result.total_tokens)
    else:
        _step("3. Contextual enrichment (rag/contextualizer.py) - SKIPPED")
        _explain("Pass --with-context to trace this step too - it makes a real LLM call")
        _explain("per chunk (real cost/latency), so it's off by default.")
        _log("rag_explain.contextualize_skipped")

    # --- 4. Embedding ---
    _step("4. Embedding (rag/embedder.py)")
    _explain(f"Converting each of the {len(final_texts)} final chunk texts into a dense")
    _explain("vector via BAAI/bge-m3, self-hosted/local (first call loads the model,")
    _explain("~2.3GB - may take a moment).")
    embeddings = await embed_documents(final_texts)
    dims = len(embeddings[0]) if embeddings else 0
    _explain(f"-> {len(embeddings)} vectors, {dims} dimensions each.")
    if embeddings:
        _explain(f"-> Sample (chunk[0], first 6 of {dims} values): {[round(v, 4) for v in embeddings[0][:6]]}")
    _log("rag_explain.embedded", vector_count=len(embeddings), dimensions=dims)

    # --- 5. Storage ---
    if subject_id:
        _step("5. Storage (rag/vector_store.py)")
        _explain(f"Upserting into Chroma's collection for subject {subject_id!r} - one")
        _explain("collection per subject, so retrieval is structurally scoped: a query")
        _explain("here can never return another subject's chunks.")
        chunk_ids = [f"rag_explain_{path.stem}_{c.index}" for c in chunks]
        metadatas = [
            {"document_id": f"rag_explain_{path.stem}", "chunk_index": c.index, "source_filename": path.name}
            for c in chunks
        ]
        await upsert_chunks(subject_id, chunk_ids, embeddings, final_texts, metadatas)
        _explain(f"-> Stored {len(chunk_ids)} chunks.")
        _explain(f'-> Try: uv run python scripts/rag_explain.py query {subject_id} "<a question about this doc>"')
        _log("rag_explain.stored", subject_id=subject_id, chunk_count=len(chunk_ids))
    else:
        _step("5. Storage (rag/vector_store.py) - SKIPPED (dry run)")
        _explain("Pass --subject-id to actually persist these chunks into Chroma - without")
        _explain("it, nothing was written anywhere.")
        _log("rag_explain.store_skipped")

    print(f"\n{'=' * 70}\nDONE\n{'=' * 70}\n")


# ---------------------------------------------------------------------------
# 2. Query trace: BM25 + dense search + RRF fusion + prompt construction
# ---------------------------------------------------------------------------


async def trace_query(subject_id: str, question: str) -> None:
    print(f"\n{'=' * 70}\nQUERY TRACE - subject={subject_id!r}  question={question!r}\n{'=' * 70}")
    _log("rag_explain.query_started", subject_id=subject_id, question=question)

    # --- 1. Load corpus ---
    _step("1. Load corpus (rag/vector_store.py: get_all_chunks)")
    _explain(f"Fetching every chunk stored for subject {subject_id!r} out of Chroma - BM25")
    _explain("needs the whole corpus to score against; the dense side doesn't (Chroma's")
    _explain("own HNSW index handles that narrowing internally, no full fetch needed).")
    corpus = await get_all_chunks(subject_id)
    _explain(f"-> {len(corpus)} chunks in this subject's corpus.")
    _log("rag_explain.corpus_loaded", chunk_count=len(corpus))
    if not corpus:
        _explain("No chunks - nothing to retrieve. Ingest a document into this subject first")
        _explain("(e.g. `ingest ... --subject-id " + subject_id + "` above).")
        return

    corpus_by_id = {c["id"]: c for c in corpus}

    # --- 2. Sparse (BM25) ---
    _step("2. Sparse search - BM25 (rag/retriever.py)")
    _explain("Tokenizing the query and every chunk (lowercase, word-splitting), then")
    _explain("scoring each chunk by term-frequency x inverse-document-frequency: shared")
    _explain("RARE words score high, shared COMMON words score close to zero.")
    from rank_bm25 import BM25Okapi

    query_tokens = _tokenize(question)
    _explain(f"-> Query tokens: {query_tokens}")
    bm25 = BM25Okapi([_tokenize(c["text"]) for c in corpus])
    sparse_scores = bm25.get_scores(query_tokens)
    ranked_sparse = sorted(
        zip((c["id"] for c in corpus), sparse_scores, strict=True), key=lambda pair: -pair[1]
    )
    _explain("-> Top BM25 matches:")
    for chunk_id, score in ranked_sparse[:5]:
        _explain(f"     {score:6.3f}  [{chunk_id}]  {_preview(corpus_by_id[chunk_id]['text'])!r}")
    sparse_ranked_ids = [chunk_id for chunk_id, _ in ranked_sparse][:_CANDIDATE_POOL_SIZE]
    _log("rag_explain.bm25_scored", query_tokens=query_tokens, top_ids=sparse_ranked_ids[:5])

    # --- 3. Dense (embeddings + Chroma) ---
    _step("3. Dense search - embeddings + Chroma (rag/embedder.py, vector_store.py)")
    _explain("Embedding the query with the same model used for chunks, then asking")
    _explain("Chroma for the nearest vectors by cosine similarity.")
    query_vector = await embed_query(question)
    dense_result = await query_similar(subject_id, query_vector, n_results=min(_CANDIDATE_POOL_SIZE, len(corpus)))
    dense_ids = dense_result["ids"][0] if dense_result.get("ids") else []
    distances_raw = dense_result.get("distances")
    dense_distances = distances_raw[0] if distances_raw else [None] * len(dense_ids)
    _explain("-> Top dense matches:")
    for chunk_id, dist in zip(dense_ids[:5], dense_distances[:5], strict=True):
        dist_str = f"{dist:6.4f}" if dist is not None else "   n/a"
        _explain(f"     dist={dist_str}  [{chunk_id}]  {_preview(corpus_by_id.get(chunk_id, {}).get('text', '?'))!r}")
    _log("rag_explain.dense_scored", top_ids=dense_ids[:5])

    # --- 4. RRF fusion ---
    _step("4. Reciprocal rank fusion (rag/retriever.py)")
    _explain(f"Merging both rankings: each chunk earns 1/(rank + {_RRF_K}) per list it")
    _explain("appears in - a chunk both methods agree on outranks one only one found.")
    fused_scores: dict[str, float] = {}
    for ranked_ids in (dense_ids, sparse_ranked_ids):
        for rank, chunk_id in enumerate(ranked_ids):
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (rank + _RRF_K)
    top_ids = sorted(fused_scores, key=lambda chunk_id: -fused_scores[chunk_id])[:5]
    _explain("-> Final fused ranking (top 5):")
    for chunk_id in top_ids:
        in_dense, in_sparse = chunk_id in dense_ids, chunk_id in sparse_ranked_ids
        agreement = "BOTH      " if in_dense and in_sparse else ("dense only" if in_dense else "sparse only")
        _explain(
            f"     {fused_scores[chunk_id]:.5f}  [{agreement}]  [{chunk_id}]  "
            f"{_preview(corpus_by_id.get(chunk_id, {}).get('text', '?'))!r}"
        )
    _log("rag_explain.fused", top_ids=top_ids)

    # --- 5. Prompt construction ---
    _step("5. Prompt construction (rag/generator.py: build_messages)")
    _explain("Building the actual messages array that would be sent to the LLM - system")
    _explain("prompt + the fused chunks as <context> + the question. See")
    _explain("docs/session-qa-notes.md Part 1 for the rest of the trip from here:")
    _explain("this -> llm_proxy client -> llm_proxy service -> HF/Groq -> generated answer.")
    retrieved = [
        RetrievedChunk(
            id=chunk_id,
            text=corpus_by_id[chunk_id]["text"],
            document_id=corpus_by_id[chunk_id]["metadata"]["document_id"],
            source_filename=corpus_by_id[chunk_id]["metadata"]["source_filename"],
        )
        for chunk_id in top_ids
        if chunk_id in corpus_by_id
    ]
    messages = build_messages(retrieved, history=[], question=question)
    system_content = messages[0]["content"]
    _explain(f"-> System message ({len(system_content)} chars, includes {len(retrieved)} chunks as <context>):")
    _explain(f"     {_preview(system_content, 300)!r}")
    _explain(f"-> Final user message: {messages[-1]!r}")
    _log("rag_explain.prompt_built", message_count=len(messages), retrieved_chunk_ids=top_ids)

    print(f"\n{'=' * 70}\nDONE\n{'=' * 70}\n")


# ---------------------------------------------------------------------------
# 3. Demo: self-contained ingest + query against a throwaway Chroma
#    testcontainer - no pre-existing infra needed beyond Docker itself.
# ---------------------------------------------------------------------------

_DEMO_SUBJECT_ID = "rag_explain_demo"


async def trace_demo(path: Path, raw_bytes: bytes, question: str, with_context: bool) -> None:
    print(f"\n{'#' * 70}\nSpinning up a throwaway Chroma container (testcontainers)...\n{'#' * 70}")
    with ChromaContainer("chromadb/chroma:1.0.0") as chroma:
        config = chroma.get_config()
        settings.chroma_host = config["host"]
        settings.chroma_port = config["port"]
        print(f"Chroma container up at {config['host']}:{config['port']} - subject_id={_DEMO_SUBJECT_ID!r}")

        await trace_ingest(path, raw_bytes, _DEMO_SUBJECT_ID, with_context)
        await trace_query(_DEMO_SUBJECT_ID, question)

    print(f"\n{'#' * 70}\nChroma container torn down - nothing persisted.\n{'#' * 70}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Explains and logs what actually happens during RAG ingest and retrieval "
        "- see docs/rag-notes.md and docs/session-qa-notes.md."
    )
    parser.add_argument("--json-log", help="also write structured JSON-lines events here (Promtail/Loki-compatible)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="trace extract -> chunk -> (contextualize) -> embed -> store")
    p_ingest.add_argument("file", help="path to a document to ingest")
    p_ingest.add_argument("--subject-id", help="actually persist chunks into this subject's Chroma collection")
    p_ingest.add_argument(
        "--with-context", action="store_true", help="also trace contextual enrichment (real LLM calls, real cost)"
    )

    p_query = sub.add_parser("query", help="trace BM25 + dense search + RRF fusion + prompt construction")
    p_query.add_argument("subject_id", help="subject to search (must already have ingested chunks)")
    p_query.add_argument("question", help="the question to retrieve for")

    p_demo = sub.add_parser(
        "demo", help="self-contained ingest + query against a throwaway Chroma testcontainer (needs only Docker)"
    )
    p_demo.add_argument("file", help="path to a document to ingest")
    p_demo.add_argument("question", help="the question to retrieve for, against what was just ingested")
    p_demo.add_argument(
        "--with-context", action="store_true", help="also trace contextual enrichment (real LLM calls, real cost)"
    )

    args = parser.parse_args()
    _setup_logging(args.json_log)

    if args.command == "ingest":
        path = Path(args.file)
        if not path.is_file():
            raise SystemExit(f"no such file: {args.file}")
        raw_bytes = path.read_bytes()
        asyncio.run(trace_ingest(path, raw_bytes, args.subject_id, args.with_context))
    elif args.command == "query":
        asyncio.run(trace_query(args.subject_id, args.question))
    elif args.command == "demo":
        path = Path(args.file)
        if not path.is_file():
            raise SystemExit(f"no such file: {args.file}")
        raw_bytes = path.read_bytes()
        asyncio.run(trace_demo(path, raw_bytes, args.question, args.with_context))


if __name__ == "__main__":
    main()
