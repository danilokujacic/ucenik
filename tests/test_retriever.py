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
