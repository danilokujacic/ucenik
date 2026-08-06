"""Splits extracted document text into overlapping, boundary-aware chunks.

Uses chonkie's RecursiveChunker: prefers paragraph breaks, falling back to
sentence, then clause/punctuation, then word boundaries - only a hard
character cut as an absolute last resort. Sized in tokens using the actual
embedding model's tokenizer (not a character-count approximation - see
docs/tokenizer-notes.md), via OverlapRefinery for the boundary-safe overlap
between consecutive chunks.
"""

from dataclasses import dataclass

from chonkie import OverlapRefinery, RecursiveChunker

from ucenik.core.config import settings

# Expensive to construct (loads the tokenizer) - build once, reuse for every document.
_chunker = RecursiveChunker(tokenizer=settings.embedding_model, chunk_size=settings.chunk_size)
# mode="token" (not "recursive"): "recursive" mode has a whitespace-
# reconstruction bug that concatenates words with no space in the overlap
# text (e.g. "Itoccursinfourmain") - "token" decodes straight from token
# IDs via the tokenizer, which is clean.
_overlap_refinery = OverlapRefinery(
    tokenizer=settings.embedding_model,
    context_size=settings.chunk_overlap,
    mode="token",
    method="suffix",
)


@dataclass
class TextChunk:
    index: int
    text: str


def chunk_text(text: str) -> list[TextChunk]:
    """Split `text` into overlapping chunks, in document order."""
    chunks = _chunker.chunk(text)
    chunks = _overlap_refinery.refine(chunks)
    return [TextChunk(index=i, text=c.text) for i, c in enumerate(chunks)]
