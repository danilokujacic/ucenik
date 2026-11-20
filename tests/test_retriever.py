"""Unit tests for rag/retriever.py's BM25 corpus cache (docs/security-
hardening.md) - get_all_chunks() and BM25Okapi's rebuild should only
happen once per subject content-version, not once per query.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import ucenik.rag.retriever as retriever_module

_CHUNKS = [
    {
        "id": "c1",
        "text": "Mitosis has four stages: prophase, metaphase, anaphase, telophase.",
        "metadata": {"document_id": "d1", "source_filename": "bio.txt"},
    },
    {
        "id": "c2",
        "text": "Photosynthesis converts light energy into chemical energy.",
        "metadata": {"document_id": "d1", "source_filename": "bio.txt"},
    },
]


async def _fake_query_similar(subject_id, query_vector, n_results):
    return {"ids": [[c["id"] for c in _CHUNKS[:n_results]]]}


async def _fake_embed_query(text):
    return [0.1, 0.2, 0.3]


def _patch_dense_side(stack: ExitStack) -> None:
    """The dense/embedding side of retrieve() isn't what these tests are
    about - patched to something harmless so each test only has to control
    get_all_chunks() and get_content_version() (the two calls the BM25
    cache actually gates).
    """
    stack.enter_context(patch.object(retriever_module, "get_all_chunks", AsyncMock(return_value=_CHUNKS)))
    stack.enter_context(patch.object(retriever_module, "embed_query", AsyncMock(side_effect=_fake_embed_query)))
    stack.enter_context(patch.object(retriever_module, "query_similar", AsyncMock(side_effect=_fake_query_similar)))


async def test_second_query_same_version_does_not_refetch_corpus():
    subject_id = "subj-cache-1"
    retriever_module._bm25_cache.clear()
    with ExitStack() as stack:
        mock_version = stack.enter_context(
            patch.object(retriever_module, "get_content_version", AsyncMock(return_value=1))
        )
        _patch_dense_side(stack)
        mock_chunks = retriever_module.get_all_chunks

        await retriever_module.retrieve(subject_id, "what are the stages of mitosis?")
        await retriever_module.retrieve(subject_id, "how does photosynthesis work?")

    assert mock_chunks.await_count == 1  # not 2 - second query hit the cache
    assert mock_version.await_count == 2  # version IS checked every time, just cheaply (Redis GET, no Chroma fetch)


async def test_version_bump_invalidates_cache():
    subject_id = "subj-cache-2"
    retriever_module._bm25_cache.clear()
    with ExitStack() as stack:
        stack.enter_context(patch.object(retriever_module, "get_content_version", AsyncMock(side_effect=[1, 2])))
        _patch_dense_side(stack)
        mock_chunks = retriever_module.get_all_chunks

        await retriever_module.retrieve(subject_id, "question one")
        await retriever_module.retrieve(subject_id, "question two")

    assert mock_chunks.await_count == 2  # version changed between calls - real refetch both times


async def test_different_subjects_cache_independently():
    retriever_module._bm25_cache.clear()
    with ExitStack() as stack:
        stack.enter_context(patch.object(retriever_module, "get_content_version", AsyncMock(return_value=1)))
        _patch_dense_side(stack)
        mock_chunks = retriever_module.get_all_chunks

        await retriever_module.retrieve("subject-a", "a question")
        await retriever_module.retrieve("subject-b", "a question")

    assert mock_chunks.await_count == 2  # different subject_id - each gets its own fetch, no cross-contamination


async def test_empty_corpus_is_not_cached_and_returns_empty_list():
    retriever_module._bm25_cache.clear()
    with (
        patch.object(retriever_module, "get_content_version", AsyncMock(return_value=1)),
        patch.object(retriever_module, "get_all_chunks", AsyncMock(return_value=[])),
    ):
        result = await retriever_module.retrieve("empty-subject", "anything")

    assert result == []
    assert "empty-subject" not in retriever_module._bm25_cache


# --- Neighbor expansion (small-to-big) --------------------------------------


def _doc_chunk(document_id: str, index: int, crumb: str) -> dict:
    return {
        "id": f"{document_id}_{index}",
        "text": f"{crumb}\nblurb\n\nchunk {index} with overlap",
        "metadata": {
            "document_id": document_id,
            "chunk_index": index,
            "source_filename": "bio.txt",
            "breadcrumb": crumb,
            "raw_text": f"[{document_id}:{index}]",
        },
    }


# d1: chunks 0-2 under "Cells", 3-5 under "Plants"; d2: a separate document
_CORPUS = [_doc_chunk("d1", i, "bio.txt > Cells" if i < 3 else "bio.txt > Plants") for i in range(6)] + [
    _doc_chunk("d2", i, "other.txt") for i in range(3)
]
_POSITIONS = {retriever_module._position(c): c for c in _CORPUS}
_BY_ID = {c["id"]: c for c in _CORPUS}


def _expand(hit_ids: list[str], window: int = 1):
    return retriever_module._expand_with_neighbors([_BY_ID[i] for i in hit_ids], _POSITIONS, window)


def test_hit_is_returned_with_its_neighbors_stitched_from_raw_text():
    [passage] = _expand(["d1_1"])
    assert passage.text == "bio.txt > Cells\n\n[d1:0][d1:1][d1:2]"
    assert passage.id == "d1_1"


def test_adjacent_hits_merge_into_one_passage_across_a_heading_boundary():
    [passage] = _expand(["d1_2", "d1_3"])
    assert passage.text == "bio.txt > Cells\n\n[d1:1][d1:2]\n\nbio.txt > Plants\n\n[d1:3][d1:4]"
    assert passage.id == "d1_2"  # the better-ranked hit names the passage


def test_a_hit_bridging_two_passages_merges_all_three():
    passages = _expand(["d1_0", "d1_4", "d1_2"])
    assert len(passages) == 1
    assert "[d1:0][d1:1][d1:2]" in passages[0].text and "[d1:3][d1:4][d1:5]" in passages[0].text


def test_hits_from_different_documents_never_merge_and_keep_rank_order():
    passages = _expand(["d2_1", "d1_1"])
    assert [p.document_id for p in passages] == ["d2", "d1"]
    assert passages[0].text == "other.txt\n\n[d2:0][d2:1][d2:2]"


def test_window_zero_disables_expansion():
    [passage] = _expand(["d1_1"], window=0)
    assert passage.text == _BY_ID["d1_1"]["text"]


def test_chunk_ingested_before_raw_text_existed_passes_through_unchanged():
    legacy = {"id": "old_0", "text": "Legacy chunk text.", "metadata": {"document_id": "old", "source_filename": "a"}}
    [passage] = retriever_module._expand_with_neighbors([legacy], _POSITIONS, 1)
    assert passage.text == "Legacy chunk text."
