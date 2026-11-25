"""Tests for rag/trace.py - the full-content RAG trace files - and the
trace events the real pipeline (rag/ingest.py, rag/retriever.py) records
into them.
"""

import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest

import ucenik.rag.ingest as ingest_module
import ucenik.rag.retriever as retriever_module
from ucenik.core.config import settings
from ucenik.llm.proxy_client import CompletionResult
from ucenik.rag import trace


def _chunk(index: int) -> dict:
    return {
        "id": f"d1_{index}",
        "text": f"bio.txt > Cells\nblurb\n\nchunk {index} about {'mitosis' if index == 1 else 'photosynthesis'}",
        "metadata": {
            "document_id": "d1",
            "chunk_index": index,
            "source_filename": "bio.txt",
            "breadcrumb": "bio.txt > Cells",
            "raw_text": f"[raw {index}]",
        },
    }


_CORPUS = [_chunk(i) for i in range(4)]


def _only_md(directory) -> str:
    [md] = list(directory.glob("*.md"))
    return md.read_text(encoding="utf-8")


def _only_json(directory) -> dict:
    [js] = list(directory.glob("*.json"))
    return json.loads(js.read_text(encoding="utf-8"))


def test_record_is_a_no_op_without_an_active_trace():
    assert not trace.active()
    trace.record("anything", huge=list(range(10)))  # must not raise or store anywhere


async def test_tracing_is_ignored_outside_development(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "rag_trace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "environment", "production")
    async with trace.rag_trace("query", "q") as t:
        assert t is None
        trace.record("question", question="q")
    assert list(tmp_path.iterdir()) == []


async def test_enabled_by_setting_in_development(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "rag_trace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "environment", "development")
    async with trace.rag_trace("query", "kako nastaje ATP?") as t:
        assert t is not None
    assert t.md_path is not None and t.md_path.exists()
    assert "query_kako-nastaje-ATP" in t.md_path.name


async def test_exception_inside_still_writes_the_file_with_the_error(tmp_path):
    with pytest.raises(RuntimeError):
        async with trace.rag_trace("ingest", "broken.pdf", out_dir=tmp_path):
            trace.record("document", filename="broken.pdf")
            raise RuntimeError("extractor exploded")
    assert not trace.active()
    md = _only_md(tmp_path)
    assert "## 2. ERROR" in md and "extractor exploded" in md


async def test_retrieve_records_every_retrieval_stage(tmp_path):
    retriever_module._bm25_cache.clear()

    async def fake_query_similar(subject_id, query_vector, n_results):
        return {"ids": [["d1_2", "d1_1"]], "distances": [[0.21, 0.35]]}

    with ExitStack() as stack:
        stack.enter_context(patch.object(retriever_module, "get_content_version", AsyncMock(return_value=1)))
        stack.enter_context(patch.object(retriever_module, "get_all_chunks", AsyncMock(return_value=_CORPUS)))
        stack.enter_context(patch.object(retriever_module, "embed_query", AsyncMock(return_value=[0.1, 0.2])))
        stack.enter_context(patch.object(retriever_module, "query_similar", AsyncMock(side_effect=fake_query_similar)))
        async with trace.rag_trace("query", "what is mitosis", out_dir=tmp_path):
            result = await retriever_module.retrieve("subj-trace", "what is mitosis", k=2)

    assert result  # tracing must not change what retrieval returns
    events = [e["event"] for e in _only_json(tmp_path)["events"]]
    assert events == ["corpus", "bm25", "dense", "rrf", "expansion"]

    data = {e["event"]: e["data"] for e in _only_json(tmp_path)["events"]}
    assert data["bm25"]["top"][0]["id"] == "d1_1"  # only chunk containing "mitosis"
    assert data["bm25"]["idf"]["mitosis"] is not None
    # d1_1 is #1 for BM25 and #2 dense -> both sides contribute
    [row] = [r for r in data["rrf"]["rows"] if r["id"] == "d1_1"]
    assert row["bm25_rank"] == 0 and row["dense_rank"] == 1 and row["selected"]
    # hits d1_1 and d1_2 are adjacent -> one merged passage
    [passage] = data["expansion"]["passages"]
    assert passage["chunk_indices"] == [0, 1, 2, 3] and passage["merged_hit_ids"]

    md = _only_md(tmp_path)
    for heading in ("BM25 (sparse) search", "Dense search", "Reciprocal rank fusion", "Neighbor expansion"):
        assert heading in md


async def test_index_document_records_what_gets_stored(tmp_path):
    upsert = AsyncMock()
    with ExitStack() as stack:
        for name, mock in {
            "get_cached_chunk": AsyncMock(return_value=None),
            "check_quota": AsyncMock(),
            "record_usage": AsyncMock(),
            "generate_context": AsyncMock(return_value=CompletionResult("A blurb.", 10, 5, 15, "test-model")),
            "embed_documents": AsyncMock(side_effect=lambda texts: [[0.5, 0.5] for _ in texts]),
            "set_cached_chunk": AsyncMock(),
            "delete_document_chunks": AsyncMock(),
            "upsert_chunks": upsert,
            "bump_subject_version": AsyncMock(),
        }.items():
            stack.enter_context(patch.object(ingest_module, name, mock))
        async with trace.rag_trace("ingest", "notes.txt", out_dir=tmp_path):
            result = await ingest_module.index_document(
                document_id="doc1",
                subject_id="subj1",
                filename="notes.txt",
                content_type="text/plain",
                raw_bytes=b"Mitosis is cell division.\n\nIt has four stages.",
                user_id="u1",
            )

    events = _only_json(tmp_path)["events"]
    names = [e["event"] for e in events]
    assert names[:3] == ["document", "extracted", "chunked"]
    assert names.count("chunk_context") == result.chunk_count
    assert names[-2:] == ["stored", "summary"]

    [stored] = [e["data"] for e in events if e["event"] == "stored"]
    # The trace shows exactly what was upserted into Chroma.
    _, ids, embeddings, texts, metadatas = upsert.call_args.args
    assert [r["id"] for r in stored["records"]] == ids
    assert [r["document"] for r in stored["records"]] == texts
    assert stored["records"][0]["document"].startswith("notes.txt\nA blurb.\n\n")
    assert "Stored in Chroma" in _only_md(tmp_path)
