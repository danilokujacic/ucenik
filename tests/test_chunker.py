"""Unit tests for rag/chunker.py's per-section chunking and
rag/contextualizer.py's document view / stored-text layout."""

from ucenik.rag.chunker import breadcrumb, chunk_sections
from ucenik.rag.contextualizer import _MAX_DOCUMENT_CHARS, _document_view, apply_context
from ucenik.rag.extractor import Section

_LONG = "Mitosis is how one cell divides into two identical daughter cells. " * 60


def test_chunks_never_cross_sections_and_carry_their_heading_path():
    sections = [Section(["Cells"], _LONG), Section(["Plants"], "Plants make food from light.")]

    chunks = chunk_sections(sections)

    assert len(chunks) > 2  # the long section really was split
    assert [c.index for c in chunks] == list(range(len(chunks)))  # continuous across sections
    assert chunks[-1].heading_path == ["Plants"]
    assert chunks[-1].raw_text == "Plants make food from light."
    assert all(c.heading_path == ["Cells"] for c in chunks[:-1])


def test_raw_texts_rejoin_to_the_original_section_text():
    """What rag/retriever.py's neighbor stitching relies on: no overlap in
    raw_text, so consecutive chunks concatenate back with nothing repeated."""
    chunks = chunk_sections([Section(["Cells"], _LONG)])

    assert "".join(c.raw_text for c in chunks) == _LONG
    # ...while `text` (what's embedded) does carry the overlap
    assert len(chunks[0].text) > len(chunks[0].raw_text)


def test_breadcrumb_starts_with_the_filename():
    assert breadcrumb("bio.pdf", ["Chapter 3", "Calvin cycle"]) == "bio.pdf > Chapter 3 > Calvin cycle"
    assert breadcrumb("notes.txt", []) == "notes.txt"


def test_short_document_is_shown_whole():
    assert _document_view("Whole short doc.", "before", "chunk", "after") == "Whole short doc."


def test_long_document_is_shown_as_opening_plus_local_window():
    opening = "TITLE AND INTRO. " * 200
    middle = "UNRELATED MIDDLE. " * 400
    document = opening + middle + "BEFORE. CHUNK ON PAGE 40. AFTER." + "TAIL. " * 100

    view = _document_view(document, "BEFORE. ", "CHUNK ON PAGE 40.", " AFTER.")

    assert view.startswith("TITLE AND INTRO.")
    assert view.endswith("BEFORE. CHUNK ON PAGE 40. AFTER.")
    assert "UNRELATED MIDDLE." not in view
    assert len(view) <= _MAX_DOCUMENT_CHARS + 20


def test_long_neighbors_are_trimmed_around_the_chunk():
    document = "x" * (_MAX_DOCUMENT_CHARS + 1)
    view = _document_view(document, "b" * 10_000, "CHUNK", "a" * 10_000)

    assert "CHUNK" in view
    assert len(view) <= _MAX_DOCUMENT_CHARS + 20


def test_stored_text_is_breadcrumb_then_blurb_then_chunk():
    assert apply_context("bio.pdf > Cells", "About mitosis.", "It has four stages.") == (
        "bio.pdf > Cells\nAbout mitosis.\n\nIt has four stages."
    )
    assert apply_context("bio.pdf", "  ", "Text.") == "bio.pdf\n\nText."
