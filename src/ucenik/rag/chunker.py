"""Splits extracted document sections into overlapping, boundary-aware chunks.

Uses chonkie's RecursiveChunker: prefers paragraph breaks, falling back to
sentence, then clause/punctuation, then word boundaries - only a hard
character cut as an absolute last resort. Sized in tokens using the actual
embedding model's tokenizer (not a character-count approximation - see
docs/tokenizer-notes.md), via OverlapRefinery for the boundary-safe overlap
between consecutive chunks.

Per section (rag/extractor.py's Section), not per whole document: a chunk
never straddles two chapters/slides/sheets, and each one carries the heading
path of the section it came from.
"""

from dataclasses import dataclass, field

from chonkie import OverlapRefinery, RecursiveChunker

from ucenik.core.config import settings
from ucenik.rag.extractor import Section

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
    """`index` is the chunk's position in the whole document (continuing
    across sections), so a chunk's neighbors are always index - 1 / + 1.

    `text` includes the overlap borrowed from the next chunk - that's what
    gets embedded, so a sentence cut at a boundary is still searchable from
    both sides. `raw_text` is the same chunk *without* that overlap:
    consecutive raw_texts concatenate back to exactly the original section
    text, which is what rag/retriever.py relies on to stitch a retrieved
    chunk and its neighbors into one clean passage with no repeated text.
    """

    index: int
    text: str
    raw_text: str
    heading_path: list[str] = field(default_factory=list)


def chunk_sections(sections: list[Section]) -> list[TextChunk]:
    """Split every section into overlapping chunks, in document order."""
    result: list[TextChunk] = []
    for section in sections:
        chunks = _chunker.chunk(section.text)
        # Captured before refining - the refinery mutates chunk text in place.
        raw_texts = [c.text for c in chunks]
        chunks = _overlap_refinery.refine(chunks)
        for chunk, raw_text in zip(chunks, raw_texts, strict=True):
            if not raw_text.strip():
                continue
            result.append(
                TextChunk(index=len(result), text=chunk.text, raw_text=raw_text, heading_path=section.heading_path)
            )
    return result


def breadcrumb(source_filename: str, heading_path: list[str]) -> str:
    """The free, deterministic context line prepended to every chunk before
    embedding, e.g. `photosynthesis.pdf > Chapter 3 > The Calvin cycle`."""
    return " > ".join([source_filename, *heading_path])
