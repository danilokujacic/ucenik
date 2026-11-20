"""Run the real RAG pipeline from the command line and get a full trace
file of everything it did - the CLI counterpart of the in-app tracing
(rag/trace.py, enabled with RAG_TRACE_DIR in .env).

Nothing here reimplements the pipeline: `ingest` calls rag/ingest.py's
index_document() and `query` calls rag/retriever.py's retrieve() plus
rag/generator.py's build_messages() - the exact code the app runs - with
tracing forced on. What you read in the trace is what the app does.

Usage:
    uv run python scripts/rag_explain.py ingest path/to/document.pdf --subject-id SUBJECT_ID
    uv run python scripts/rag_explain.py query SUBJECT_ID "question text"
    uv run python scripts/rag_explain.py --out-dir /some/dir query SUBJECT_ID "question text"

Needs running: Chroma + Redis (`docker compose up -d chromadb redis`) and
the embedding service (`make embedding-service`); `ingest` also needs the
LLM proxy (`make llm-proxy`) for the per-chunk context blurbs. No Mongo:
`ingest` stores chunks under document id `rag_explain_<file stem>` without
creating a Document record, so it won't show up in the app's document list
- re-running it replaces that document's chunks. LLM usage is counted
against a pseudo user `rag_explain`.

`query` stops before the LLM: the trace ends with the exact prompt that
would be sent. Use the app itself (with RAG_TRACE_DIR set) to trace a
question all the way through to the answer.
"""

import argparse
import asyncio
from pathlib import Path

from ucenik.core.redis import close_redis, init_redis
from ucenik.rag import trace
from ucenik.rag.extractor import _DOCX_CONTENT_TYPE, _PPTX_CONTENT_TYPE, _XLSX_CONTENT_TYPE
from ucenik.rag.generator import build_messages
from ucenik.rag.ingest import index_document
from ucenik.rag.retriever import retrieve

_CONTENT_TYPE_BY_SUFFIX = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": _DOCX_CONTENT_TYPE,
    ".pptx": _PPTX_CONTENT_TYPE,
    ".xlsx": _XLSX_CONTENT_TYPE,
}


async def run_ingest(path: Path, raw_bytes: bytes, content_type: str, subject_id: str, out_dir: str) -> None:
    async with trace.rag_trace("ingest", path.name, out_dir=out_dir) as t:
        result = await index_document(
            document_id=f"rag_explain_{path.stem}",
            subject_id=subject_id,
            filename=path.name,
            content_type=content_type,
            raw_bytes=raw_bytes,
            user_id="rag_explain",
        )
    print(f"{result.chunk_count} chunks stored ({result.cache_hits} cache hits, {result.cache_misses} misses)")
    print(f"trace: {t.md_path}")


async def run_query(subject_id: str, question: str, out_dir: str) -> None:
    async with trace.rag_trace("query", question, out_dir=out_dir) as t:
        trace.record("question", session_id="(rag_explain - no session)", question=question, history=[])
        chunks = await retrieve(subject_id, question)
        trace.record(
            "prompt",
            note="What the app would send to the LLM for this question (first question of a session, no history).",
            messages=build_messages(chunks, history=[], question=question),
        )
    print(f"{len(chunks)} passage(s) retrieved")
    print(f"trace: {t.md_path}")


async def main_async(args: argparse.Namespace, ingest_input: tuple[Path, bytes, str] | None) -> None:
    await init_redis()
    try:
        if ingest_input is not None:
            await run_ingest(*ingest_input, args.subject_id, args.out_dir)
        else:
            await run_query(args.subject_id, args.question, args.out_dir)
    finally:
        await close_redis()


def _read_ingest_input(file: str) -> tuple[Path, bytes, str]:
    path = Path(file)
    if not path.is_file():
        raise SystemExit(f"no such file: {file}")
    content_type = _CONTENT_TYPE_BY_SUFFIX.get(path.suffix.lower())
    if content_type is None:
        supported = ", ".join(sorted(_CONTENT_TYPE_BY_SUFFIX))
        raise SystemExit(f"unsupported file type {path.suffix!r} - supported: {supported}")
    return path, path.read_bytes(), content_type


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the real RAG pipeline and write a full trace file.")
    parser.add_argument("--out-dir", default="rag_traces", help="where to write trace files (default: rag_traces)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="extract -> chunk -> contextualize -> embed -> store, traced")
    p_ingest.add_argument("file", help="document to ingest (.txt/.pdf/.docx/.pptx/.xlsx)")
    p_ingest.add_argument("--subject-id", required=True, help="subject whose Chroma collection to store into")

    p_query = sub.add_parser("query", help="BM25 + dense + RRF + neighbor expansion + prompt, traced")
    p_query.add_argument("subject_id", help="subject to search (must already have ingested chunks)")
    p_query.add_argument("question", help="the question to retrieve for")

    args = parser.parse_args()
    ingest_input = _read_ingest_input(args.file) if args.command == "ingest" else None
    asyncio.run(main_async(args, ingest_input))


if __name__ == "__main__":
    main()
