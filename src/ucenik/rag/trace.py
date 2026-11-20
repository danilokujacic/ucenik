"""Full-content RAG trace files - one readable Markdown file (plus the raw
JSON) per document upload and per Tutor question, showing the actual data
at every step: extracted sections, chunks, the exact LLM prompts and
blurbs, embedded text and vectors, what got stored in Chroma, BM25/dense
scores, RRF fusion, neighbor expansion, the final generator prompt and the
answer.

Why a separate mechanism from core/logging_config.py's JSON logs: those
are one-line summary events meant for Grafana dashboards ("ingest took
4.2s, 42 chunks"); this is the full content, meant for a human reading one
run end to end to understand (or debug) what the pipeline actually did.

How it works:
  - rag_trace(kind, name) is an async context manager that makes a
    RagTrace "current" for everything awaited inside it (a ContextVar, so
    concurrent uploads/questions each get their own trace).
  - Pipeline code calls record("event_name", **data) at each step - a
    no-op returning immediately when no trace is current, which is the
    default and always the case in production.
  - The two network clients (llm/proxy_client.py, rag/embedder.py) record
    every call automatically, so prompts are captured exactly as sent.
  - On exit, events are written as `<timestamp>_<kind>_<name>.md` + `.json`.

Enabled by settings.rag_trace_dir, ONLY when settings.environment is
"development" - trace files contain document text and student questions,
so this fails closed rather than ever writing them in production.
scripts/rag_explain.py forces it on via `out_dir` instead.
"""

import html
import json
import logging
import math
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ucenik.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RagTrace:
    kind: str  # "ingest" | "query"
    name: str  # filename or question - shown in the title, slugged into the file name
    out_dir: Path
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    events: list[dict[str, Any]] = field(default_factory=list)
    md_path: Path | None = None  # set once written
    _t0: float = field(default_factory=time.perf_counter)

    def record(self, event: str, data: dict[str, Any]) -> None:
        elapsed_ms = round((time.perf_counter() - self._t0) * 1000, 1)
        self.events.append({"event": event, "elapsed_ms": elapsed_ms, "data": data})


_current: ContextVar[RagTrace | None] = ContextVar("rag_trace", default=None)


def active() -> bool:
    """For callers whose trace payload is expensive to build - check this
    first rather than building it only for record() to throw it away."""
    return _current.get() is not None


def record(event: str, **data: Any) -> None:
    trace = _current.get()
    if trace is not None:
        trace.record(event, data)


def _resolve_dir(out_dir: str | Path | None) -> Path | None:
    if out_dir is not None:
        return Path(out_dir)
    if settings.rag_trace_dir and settings.environment == "development":
        return Path(settings.rag_trace_dir)
    return None


@asynccontextmanager
async def rag_trace(kind: str, name: str, *, out_dir: str | Path | None = None) -> AsyncIterator[RagTrace | None]:
    """Yields the RagTrace, or None when tracing is off (nothing recorded,
    nothing written). An exception inside is recorded as an "error" event
    and re-raised - a failed run is exactly when you want the trace file.
    """
    directory = _resolve_dir(out_dir)
    if directory is None:
        yield None
        return

    trace = RagTrace(kind=kind, name=name, out_dir=directory)
    token = _current.set(trace)
    try:
        yield trace
    except BaseException as exc:
        # BaseException, not Exception: a client disconnecting mid-answer
        # closes services/chat.py's stream generator (GeneratorExit) - worth
        # seeing in the trace as "interrupted" rather than a silently
        # truncated file.
        trace.record("error", {"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        try:
            _current.reset(token)
        except ValueError:
            # Closed from a different context than it was opened in (an
            # async generator finalized by the event loop) - reset() refuses
            # that, so just clear it.
            _current.set(None)
        # Plain synchronous write, not asyncio.to_thread: this may run while
        # a generator is being closed, where awaiting is unreliable, and a
        # few hundred KB is milliseconds anyway.
        _write(trace)


def _write(trace: RagTrace) -> None:
    """Never lets a trace problem break the real pipeline - a failed write
    is logged and otherwise ignored."""
    try:
        trace.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = trace.started_at.strftime("%Y-%m-%dT%H-%M-%S.%f")[:-3]
        slug = re.sub(r"[^\w.-]+", "-", trace.name, flags=re.UNICODE).strip("-")[:60] or "untitled"
        base = trace.out_dir / f"{stamp}_{trace.kind}_{slug}"
        md_path = base.with_name(base.name + ".md")
        json_path = base.with_name(base.name + ".json")
        json_path.write_text(
            json.dumps(
                {
                    "kind": trace.kind,
                    "name": trace.name,
                    "started_at": trace.started_at.isoformat(),
                    "events": trace.events,
                },
                ensure_ascii=False,
                indent=1,
                default=str,
            ),
            encoding="utf-8",
        )
        md_path.write_text(render_markdown(trace), encoding="utf-8")
        trace.md_path = md_path
        logger.info("rag_trace.written", extra={"event": "rag_trace.written", "path": str(md_path)})
    except Exception as exc:
        logger.warning("rag_trace.write_failed", extra={"event": "rag_trace.write_failed", "error": str(exc)})


# ---------------------------------------------------------------------------
# Markdown rendering - one small function per event type. Long text always
# goes in a collapsed <details> block so the file stays scannable in VS
# Code's Markdown preview (Ctrl+Shift+V); click to expand what you need.
# ---------------------------------------------------------------------------


def _block(text: str, lang: str = "text") -> str:
    # Fence longer than any backtick run inside, so chunk text containing
    # ``` (code samples in course material) can't end the block early.
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text}\n{fence}"


def _details(summary: str, body: str, *, open_: bool = False) -> str:
    return f"<details{' open' if open_ else ''}><summary>{html.escape(summary)}</summary>\n\n{body}\n\n</details>"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _preview(text: str, n: int = 110) -> str:
    flat = " ".join(text.split())
    return flat[:n] + ("…" if len(flat) > n else "")


def _vector(vector: list[float]) -> str:
    norm = math.sqrt(sum(v * v for v in vector))
    head = ", ".join(f"{v:.4f}" for v in vector[:8])
    return f"{len(vector)} dims, L2 norm {norm:.4f}, first 8: [{head}, …]"


def _json(value: Any) -> str:
    return _block(json.dumps(value, ensure_ascii=False, indent=2, default=str), "json")


def _messages(messages: list[dict[str, str]]) -> str:
    parts = []
    for i, m in enumerate(messages):
        content = m.get("content", "")
        parts.append(_details(f"message {i}: {m.get('role')} ({len(content)} chars)", _block(content)))
    return "\n\n".join(parts)


def _r_document(d: dict) -> str:
    return "\n".join(f"- **{k}**: `{v}`" for k, v in d.items())


def _r_extracted(d: dict) -> str:
    sections = d["sections"]
    out = [
        f"The extractor (rag/extractor.py) split the file into **{len(sections)} sections**. "
        "Each section's heading path comes from PDF bookmarks / docx headings / slide titles / sheet names."
    ]
    for i, s in enumerate(sections):
        path = " > ".join(s["heading_path"]) or "(no heading)"
        out.append(_details(f"section {i}: [{path}] - {len(s['text'])} chars", _block(s["text"])))
    out.append(
        _details(
            f"render_sections() output - the whole-document text the blurb LLM reads ({len(d['document_text'])} chars)",
            _block(d["document_text"]),
        )
    )
    return "\n\n".join(out)


def _r_chunked(d: dict) -> str:
    chunks = d["chunks"]
    out = [
        f"The chunker (rag/chunker.py) produced **{len(chunks)} chunks** "
        f"(chunk_size={d['chunk_size']} tokens, overlap={d['chunk_overlap']} tokens). "
        "`raw_text` is the chunk itself; `overlap` is the tail borrowed from the next chunk, "
        "appended so a sentence cut at the boundary is searchable from both sides. "
        "Embedded text = raw_text + overlap.",
    ]
    table = ["| # | heading path | raw_text chars | overlap chars | starts with |", "|---|---|---|---|---|"]
    for c in chunks:
        table.append(
            f"| {c['index']} | {_cell(' > '.join(c['heading_path']) or '-')} | {len(c['raw_text'])} "
            f"| {len(c['overlap'])} | {_cell(_preview(c['raw_text'], 60))} |"
        )
    out.append("\n".join(table))
    for c in chunks:
        body = f"**raw_text**\n\n{_block(c['raw_text'])}\n\n**overlap (borrowed from next chunk)**\n\n" + (
            _block(c["overlap"]) if c["overlap"] else "_(none - last chunk of its section)_"
        )
        out.append(_details(f"chunk[{c['index']}] full text", body))
    return "\n\n".join(out)


def _r_llm_call(d: dict) -> str:
    if "error" in d:
        return f"**LLM call FAILED**: `{d['error']}`\n\n{_messages(d['messages'])}"
    head = (
        f"model `{d['model']}`, temperature {d['temperature']}, max_tokens {d['max_tokens']} - "
        f"{d['prompt_tokens']} prompt + {d['completion_tokens']} completion = **{d['total_tokens']} tokens**, "
        f"{d['duration_ms']} ms"
    )
    return f"{head}\n\n{_messages(d['messages'])}\n\n**response**\n\n{_block(d['response'])}"


def _r_llm_call_stream(d: dict) -> str:
    return (
        f"Streaming request - model `{d['model']}`, temperature {d['temperature']}, max_tokens "
        f"{d['max_tokens']}. These are the exact messages sent (the system message holds the retrieved "
        f"passages inside the randomized context tag):\n\n{_messages(d['messages'])}"
    )


def _r_prompt(d: dict) -> str:
    return f"{d.get('note', '')}\n\n{_messages(d['messages'])}"


def _r_chunk_context(d: dict) -> str:
    cache = (
        "cache **HIT** - blurb and embedding restored from Redis, no LLM or embedding call"
        if d["cache"] == "hit"
        else f"cache **MISS** - blurb generated by the LLM call above ({d['tokens']} tokens)"
    )
    return f"- breadcrumb: `{d['breadcrumb']}`\n- {cache}\n- blurb:\n\n{_block(d['blurb'] or '(empty)')}"


def _r_embedding_call(d: dict) -> str:
    texts, vectors = d["texts"], d["vectors"]
    out = [
        f"Sent **{len(texts)} text(s)** to the embedding service (prompt_name=`{d['prompt_name']}` - "
        "BGE-M3 embeds queries and documents slightly differently). Each text became one vector; "
        "full vectors are in the .json file."
    ]
    for i, (text, vector) in enumerate(zip(texts, vectors, strict=False)):
        out.append(f"- [{i}] `{_cell(_preview(text, 80))}` → {_vector(vector)}")
    return "\n".join(out)


def _r_stored(d: dict) -> str:
    records = d["records"]
    out = [
        f"Deleted any old chunks of document `{d['document_id']}` from Chroma collection "
        f"`subject_{d['subject_id']}`, then upserted **{len(records)} records**. This is everything "
        "retrieval will ever see for this document: `document` is the text BM25 scores and the dense "
        "vector was computed from (breadcrumb + blurb + chunk); `metadata.raw_text` is used for "
        "neighbor stitching."
    ]
    for r in records:
        body = (
            f"**id**: `{r['id']}`\n\n**embedding**: {_vector(r['embedding'])}\n\n"
            f"**document** (stored + embedded text)\n\n{_block(r['document'])}\n\n"
            f"**metadata**\n\n{_json(r['metadata'])}"
        )
        out.append(_details(f"{r['id']} - {_preview(r['document'], 70)}", body))
    return "\n\n".join(out)


def _r_summary(d: dict) -> str:
    return "\n".join(f"- **{k}**: {v}" for k, v in d.items())


def _r_question(d: dict) -> str:
    history = d["history"]
    out = [f"**Question**: {d['question']}", f"Session `{d['session_id']}`, {len(history)} prior message(s)."]
    if history:
        out.append(_details("history replayed into the prompt", _json(history)))
    return "\n\n".join(out)


def _r_answer_cache(d: dict) -> str:
    return {
        "hit": "**HIT** - this exact first question was answered before for this subject; the cached "
        "answer is replayed, no retrieval or LLM call happens.",
        "miss": "**MISS** - first question of the session but not cached yet; full pipeline runs.",
        "not_cacheable": "**Not cacheable** - the session already has messages, so the answer depends "
        "on history; full pipeline runs.",
    }[d["status"]]


def _r_rewrite(d: dict) -> str:
    text = {
        "skipped": "Skipped - first question of the session, nothing to resolve against.",
        "rewritten": "The LLM call above rewrote the follow-up into a standalone search query.",
        "unchanged": "The rewriter returned the question unchanged (already standalone, or output rejected).",
        "failed": "Rewrite call failed - falling back to the original question.",
    }[d["status"]]
    return f"{text}\n\n- original: `{d['original']}`\n- **search query**: `{d['search_query']}`"


def _r_corpus(d: dict) -> str:
    how = (
        "BM25 index reused from the in-process cache"
        if d["bm25_cache"] == "hit"
        else "fetched every chunk from Chroma and rebuilt the BM25 index"
    )
    return (
        f"Subject `{d['subject_id']}`: **{d['chunk_count']} chunks** (content version {d['content_version']}) - {how}."
    )


def _r_bm25(d: dict) -> str:
    out = [
        "BM25 (sparse search) lowercases and splits the query into word tokens, then scores every chunk "
        "by how often it contains them, weighted by IDF: rare tokens count a lot, common ones almost "
        "nothing, tokens not in any chunk count zero. No synonyms, no morphology - `ćelija` and `ćelije` "
        "are different tokens.",
        "",
        "| query token | IDF |",
        "|---|---|",
    ]
    for token in d["query_tokens"]:
        idf = d["idf"].get(token)
        out.append(f"| `{token}` | {'not in corpus' if idf is None else f'{idf:.3f}'} |")
    out += ["", "| rank | score | chunk | text |", "|---|---|---|---|"]
    for i, row in enumerate(d["top"]):
        out.append(f"| {i} | {row['score']:.3f} | `{row['id']}` | {_cell(row['preview'])} |")
    return "\n".join(out)


def _r_dense(d: dict) -> str:
    out = [
        "Dense search: the query vector (embedding call above) is compared to every stored vector by "
        "cosine distance (0 = same direction, lower is better; similarity = 1 - distance). Finds "
        "matches by meaning even with no shared words.",
        "",
        "| rank | distance | similarity | chunk | text |",
        "|---|---|---|---|---|",
    ]
    for i, row in enumerate(d["top"]):
        dist = row["distance"]
        dist_s, sim_s = ("n/a", "n/a") if dist is None else (f"{dist:.4f}", f"{1 - dist:.4f}")
        out.append(f"| {i} | {dist_s} | {sim_s} | `{row['id']}` | {_cell(row['preview'])} |")
    return "\n".join(out)


def _r_rrf(d: dict) -> str:
    k = d["rrf_k"]
    out = [
        f"Reciprocal rank fusion: each chunk scores 1/(rank + {k}) for each list it appears in, summed. "
        "Only ranks matter, not raw scores (BM25 scores and cosine distances aren't comparable). A chunk "
        f"both searches found beats one only one side found. Top **{d['top_k']}** go on.",
        "",
        "| fused | dense rank | +dense | bm25 rank | +bm25 | chunk | selected |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in d["rows"]:

        def rank(r: int | None) -> str:
            return "-" if r is None else str(r)

        out.append(
            f"| {row['score']:.5f} | {rank(row['dense_rank'])} | {row['dense_contrib']:.5f} "
            f"| {rank(row['bm25_rank'])} | {row['bm25_contrib']:.5f} | `{row['id']}` "
            f"| {'✅' if row['selected'] else ''} |"
        )
    return "\n".join(out)


def _r_expansion(d: dict) -> str:
    passages = d["passages"]
    out = [
        f"Small-to-big: each selected hit is widened by up to {d['window']} neighboring chunk(s) on each "
        "side, stitched from overlap-free raw_text; overlapping windows in the same document merge into "
        f"one passage. Result: **{len(passages)} passage(s)** handed to the generator."
    ]
    for i, p in enumerate(passages):
        merged = f", merged in hits {', '.join(f'`{h}`' for h in p['merged_hit_ids'])}" if p["merged_hit_ids"] else ""
        indices = p["chunk_indices"] if p["chunk_indices"] is not None else "legacy chunk - passed through as-is"
        body = f"built around hit `{p['hit_id']}`{merged}; chunk indices {indices}\n\n{_block(p['text'])}"
        out.append(_details(f"passage {i}: {p['source_filename']} ({len(p['text'])} chars)", body, open_=i == 0))
    return "\n\n".join(out)


def _r_answer(d: dict) -> str:
    sources = ", ".join(f"`{s['source_filename']}`" for s in d["sources"]) or "(none)"
    return f"{_block(d['content'])}\n\n- usage: `{d['usage']}`\n- sources cited: {sources}"


def _r_error(d: dict) -> str:
    return f"**{d['type']}**: {d['message']}"


_RENDERERS: dict[str, tuple[str, Callable[[dict], str]]] = {
    "document": ("Document", _r_document),
    "extracted": ("Extraction", _r_extracted),
    "chunked": ("Chunking", _r_chunked),
    "llm_call": ("LLM call", _r_llm_call),
    "llm_call_stream": ("LLM call (streaming) - generator prompt", _r_llm_call_stream),
    "prompt": ("Generator prompt (not sent)", _r_prompt),
    "chunk_context": ("Context", _r_chunk_context),
    "embedding_call": ("Embedding call", _r_embedding_call),
    "stored": ("Stored in Chroma", _r_stored),
    "summary": ("Summary", _r_summary),
    "question": ("Question", _r_question),
    "answer_cache": ("Answer cache", _r_answer_cache),
    "rewrite": ("Query rewrite", _r_rewrite),
    "corpus": ("Corpus", _r_corpus),
    "bm25": ("BM25 (sparse) search", _r_bm25),
    "dense": ("Dense search", _r_dense),
    "rrf": ("Reciprocal rank fusion", _r_rrf),
    "expansion": ("Neighbor expansion", _r_expansion),
    "answer": ("Answer", _r_answer),
    "error": ("ERROR", _r_error),
}


def render_markdown(trace: RagTrace) -> str:
    out = [
        f"# {trace.kind.capitalize()} trace: {trace.name}",
        f"Started {trace.started_at.isoformat(timespec='seconds')} · {len(trace.events)} events · "
        f"`+ms` = time since start. Raw data (incl. full vectors) in the matching `.json` file.",
    ]
    for n, event in enumerate(trace.events, start=1):
        title, render = _RENDERERS.get(event["event"], (event["event"], _json))
        data = event["data"]
        if event["event"] == "chunk_context":
            title = f"Context for chunk[{data['index']}]"
        try:
            body = render(data)
        except Exception as exc:  # a renderer bug shouldn't lose the rest of the file
            body = f"_(render failed: {exc})_\n\n{_json(data)}"
        out.append(f"## {n}. {title} `+{event['elapsed_ms']}ms`\n\n{body}")
    return "\n\n".join(out) + "\n"
