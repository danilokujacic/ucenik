"""Hybrid retrieval (dense + BM25) for the Tutor query flow (§Phase 5, see
docs/rag-notes.md's "Hybrid search" section).

Dense embeddings are great at semantic matching but can miss exact terms
(a rare acronym, a specific formula, a proper noun the model never learned
to weight); BM25 is the reverse - bad at meaning, excellent at "this exact
word appears." Running both and merging catches what either alone misses.

BM25 corpus caching (docs/security-hardening.md): every query used to
re-fetch a subject's *entire* corpus out of Chroma and rebuild a fresh
BM25Okapi index from scratch, even for the same subject asked ten questions
in a row with nothing re-ingested in between - real, uncapped CPU/memory
work with no cost ceiling beyond the generic per-IP rate limit. Now cached
per-process (module-level dict, not Redis - a BM25Okapi object isn't
trivially serializable, and `app`/`worker` each retrieving independently is
fine at this cost, unlike the embedding-model duplication embedding_service
exists to avoid), keyed on the subject's content version
(cache/chat_cache.py's get_content_version() - the exact same signal
already bumped on every ingest/delete, reused rather than inventing a
second invalidation scheme).

Small-to-big (neighbor expansion, see _expand_with_neighbors): search runs
over small chunks because small chunks match precisely, but a small chunk
is often too little to answer from ("It takes place in the stroma" - what
does?). So each hit is handed to the generator stitched together with the
chunks right before and after it in its document
(settings.retrieval_neighbor_window on each side), using the chunks'
overlap-free raw_text so the passage reads as one continuous excerpt.
Overlapping passages from the same document are merged rather than
repeated. Search itself is unchanged - only what's returned for each hit.
"""

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from ucenik.cache.chat_cache import get_content_version
from ucenik.core.config import settings
from ucenik.rag.embedder import embed_query
from ucenik.rag.vector_store import get_all_chunks, query_similar

# (document_id, chunk_index) -> chunk, for neighbor lookup
_Positions = dict[tuple[str, int], dict]

_bm25_cache: dict[str, tuple[int, list[dict], BM25Okapi, _Positions]] = {}

# How many candidates each side of the hybrid search contributes to the
# fusion pool, before trimming down to the final `k` returned to the caller.
# Wider than the final k so fusion actually has something to fuse - if both
# sides only ever returned k candidates each, a chunk ranked k+1 by one side
# but #1 by the other would never get the chance to surface.
_CANDIDATE_POOL_SIZE = 20

# Reciprocal rank fusion constant - standard default from the RRF literature.
# Higher values flatten the influence of rank position; 60 is the commonly
# cited sweet spot and not something this project has a reason to tune yet.
_RRF_K = 60

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


@dataclass
class RetrievedChunk:
    id: str
    text: str
    document_id: str
    source_filename: str


def _tokenize(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


async def _get_corpus_and_bm25(subject_id: str) -> tuple[list[dict], BM25Okapi, _Positions] | None:
    """Cache hit: skips both the Chroma fetch and the BM25Okapi rebuild.
    Cache miss (nothing cached yet, or the subject's content version moved
    since the last cache) - fetch + rebuild once, cache the result under
    the version that was current at fetch time.
    """
    version = await get_content_version(subject_id)
    cached = _bm25_cache.get(subject_id)
    if cached is not None and cached[0] == version:
        return cached[1], cached[2], cached[3]

    corpus = await get_all_chunks(subject_id)
    if not corpus:
        _bm25_cache.pop(subject_id, None)
        return None

    bm25 = BM25Okapi([_tokenize(chunk["text"]) for chunk in corpus])
    positions = {position: chunk for chunk in corpus if (position := _position(chunk)) is not None}
    _bm25_cache[subject_id] = (version, corpus, bm25, positions)
    return corpus, bm25, positions


async def retrieve(subject_id: str, query: str, k: int = 5) -> list[RetrievedChunk]:
    """Top-`k` chunks for `query`, scoped to one subject's collection.

    Returns an empty list if the subject has no ingested chunks at all - the
    caller (rag/generator.py) is expected to treat that as "nothing to
    ground an answer in" and say so honestly, not silently answer from the
    model's own knowledge (see docs/rag-notes.md's "honest failure" note).
    """
    cached = await _get_corpus_and_bm25(subject_id)
    if cached is None:
        return []
    corpus, bm25, positions = cached

    corpus_by_id = {chunk["id"]: chunk for chunk in corpus}

    # Sparse side: BM25 over every chunk's raw text - see _get_corpus_and_bm25
    # for the caching that now avoids rebuilding this on every single query.
    sparse_scores = bm25.get_scores(_tokenize(query))
    sparse_ranked_ids = [
        chunk_id
        for chunk_id, _ in sorted(zip((c["id"] for c in corpus), sparse_scores, strict=True), key=lambda pair: -pair[1])
    ][:_CANDIDATE_POOL_SIZE]

    # Dense side: cosine similarity via Chroma's index.
    query_vector = await embed_query(query)
    dense_result = await query_similar(subject_id, query_vector, n_results=min(_CANDIDATE_POOL_SIZE, len(corpus)))
    dense_ranked_ids = dense_result["ids"][0] if dense_result["ids"] else []

    # Reciprocal rank fusion: score each id by 1/(rank + K) per list it
    # appears in, summed across lists. A chunk both searches agree on scores
    # higher than one only one side found - that's the whole point of hybrid.
    fused_scores: dict[str, float] = {}
    for ranked_ids in (dense_ranked_ids, sparse_ranked_ids):
        for rank, chunk_id in enumerate(ranked_ids):
            fused_scores[chunk_id] = fused_scores.get(chunk_id, 0.0) + 1.0 / (rank + _RRF_K)

    top_ids = sorted(fused_scores, key=lambda chunk_id: -fused_scores[chunk_id])[:k]
    hits = [corpus_by_id[chunk_id] for chunk_id in top_ids if chunk_id in corpus_by_id]
    return _expand_with_neighbors(hits, positions, settings.retrieval_neighbor_window)


def _position(chunk: dict) -> tuple[str, int] | None:
    """Where a chunk sits in its document - None for a chunk ingested before
    raw_text was stored (rag/ingest.py), which can't be stitched cleanly and
    is passed through as-is instead.
    """
    metadata = chunk["metadata"]
    if "raw_text" not in metadata or "chunk_index" not in metadata:
        return None
    return metadata["document_id"], metadata["chunk_index"]


@dataclass
class _Passage:
    hit: dict  # the best-ranked search hit this passage was built around
    indices: set[int] | None  # chunk_index values to stitch; None = legacy, use hit text as-is


def _expand_with_neighbors(hits: list[dict], positions: _Positions, window: int) -> list[RetrievedChunk]:
    """One passage per hit, in rank order: the hit plus up to `window`
    neighbors on each side. A hit whose window overlaps an earlier
    passage's (same document) is merged into it instead - so two adjacent
    hits become one longer passage, never two that repeat each other.
    """
    passages: list[_Passage] = []
    for hit in hits:
        position = _position(hit)
        if position is None or window <= 0:
            passages.append(_Passage(hit=hit, indices=None))
            continue
        document_id, index = position
        wanted = {i for i in range(index - window, index + window + 1) if (document_id, i) in positions}
        passages.append(_Passage(hit=hit, indices=wanted))

    # Merge until stable - one merge can make a passage overlap another one
    # it didn't before (a hit bridging two previously separate passages).
    merged = True
    while merged:
        merged = False
        for a, first in enumerate(passages):
            for b in range(a + 1, len(passages)):
                second = passages[b]
                if (
                    first.indices is not None
                    and second.indices is not None
                    and first.hit["metadata"]["document_id"] == second.hit["metadata"]["document_id"]
                    and first.indices & second.indices
                ):
                    first.indices |= second.indices
                    del passages[b]
                    merged = True
                    break
            if merged:
                break

    return [
        RetrievedChunk(
            id=p.hit["id"],
            text=_passage_text(p, positions),
            document_id=p.hit["metadata"]["document_id"],
            source_filename=p.hit["metadata"]["source_filename"],
        )
        for p in passages
    ]


def _passage_text(passage: _Passage, positions: _Positions) -> str:
    if passage.indices is None:
        return passage.hit["text"]
    return _stitch(passage.hit["metadata"]["document_id"], passage.indices, positions)


def _stitch(document_id: str, indices: set[int], positions: _Positions) -> str:
    """Consecutive raw_texts concatenate back to the original text exactly
    (rag/chunker.py), so the passage reads as one excerpt. Each run of
    chunks from one section is introduced by its breadcrumb - a passage
    crossing a heading boundary shows both headings where they apply.
    """
    parts: list[str] = []
    current_breadcrumb: str | None = None
    for i in sorted(indices):
        metadata = positions[(document_id, i)]["metadata"]
        crumb = metadata.get("breadcrumb") or ""
        if crumb != current_breadcrumb:
            if parts:
                parts.append("\n\n")
            if crumb:
                parts.append(f"{crumb}\n\n")
            current_breadcrumb = crumb
        parts.append(metadata["raw_text"])
    return "".join(parts).strip()
