"""Unit tests for rag/extractor.py's per-page OCR fallback
(_extract_pdf_text) - no DB/HTTP machinery needed, these call
extract_text() directly. The end-to-end "PDF with a real text layer" path
is already covered by test_documents.py's ingest tests; these isolate the
per-page branching (text vs. needs-OCR vs. broken) specifically.
"""

import io
from unittest.mock import MagicMock, patch

import pytesseract
import pytest
from pypdf import PdfWriter

from ucenik.rag.extractor import Section, UnsupportedDocumentError, extract_sections, extract_text, render_sections

# A Private Use Area codepoint, like a symbol font's raw glyph code for "∧"
# would extract as (see rag/extractor.py's _PRIVATE_USE_AREA docstring) -
# spelled out via chr() rather than a literal char in this file, so the
# invisible-by-design codepoint is actually visible/reviewable in source.
_PUA_GLYPH = chr(0xF02D)


def _blank_pdf_bytes(pages: int = 1) -> bytes:
    """A structurally valid PDF with zero extractable text on every page -
    pypdf's own extract_text() returns "" for all of them, same shape as a
    real scanned PDF with no text layer, without needing a real scanned
    fixture. Used for the "every page needs OCR" tests below.
    """
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _fake_reader(page_texts: list[str | None]) -> MagicMock:
    """A fake PdfReader whose pages have controllable, independent
    extract_text() behavior - `None` means that page's extract_text()
    raises (simulating a corrupt content stream), a string (possibly empty)
    means it returns that. Used for the mixed-content and broken-page
    tests, where building a real PDF with heterogeneous per-page content
    would be impractical - these tests are about this module's branching
    logic, not pypdf's own parsing fidelity.
    """
    pages = []
    for text in page_texts:
        page = MagicMock()
        if text is None:
            page.extract_text.side_effect = RuntimeError("corrupt content stream")
        else:
            page.extract_text.return_value = text
        pages.append(page)
    reader = MagicMock()
    reader.pages = pages
    return reader


async def test_no_text_layer_falls_back_to_ocr_and_succeeds():
    pdf_bytes = _blank_pdf_bytes()
    with (
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]) as mock_convert,
        patch("ucenik.rag.extractor.pytesseract.image_to_string", return_value="Recognized text.") as mock_ocr,
    ):
        text = await extract_text("application/pdf", pdf_bytes)

    assert text == "Recognized text."
    mock_convert.assert_called_once_with(pdf_bytes, dpi=300, first_page=1, last_page=1, grayscale=True)
    mock_ocr.assert_called_once_with("fake-image")


async def test_ocr_finding_nothing_either_raises_unsupported():
    with (
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]),
        patch("ucenik.rag.extractor.pytesseract.image_to_string", return_value="   "),
        pytest.raises(UnsupportedDocumentError, match="even after OCR"),
    ):
        await extract_text("application/pdf", _blank_pdf_bytes())


async def test_missing_tesseract_binary_raises_a_distinct_unsupported_error():
    with (
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]),
        patch(
            "ucenik.rag.extractor.pytesseract.image_to_string",
            side_effect=pytesseract.TesseractNotFoundError(),
        ),
        pytest.raises(UnsupportedDocumentError, match="isn't installed"),
    ):
        await extract_text("application/pdf", _blank_pdf_bytes())


async def test_missing_tesseract_stops_after_first_page_not_retried_per_page():
    """Once Tesseract is known to be unavailable, every remaining page would
    fail identically - no reason to keep attempting them one by one.
    """
    with (
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]) as mock_convert,
        patch(
            "ucenik.rag.extractor.pytesseract.image_to_string",
            side_effect=pytesseract.TesseractNotFoundError(),
        ),
        pytest.raises(UnsupportedDocumentError, match="isn't installed"),
    ):
        await extract_text("application/pdf", _blank_pdf_bytes(pages=5))

    mock_convert.assert_called_once()  # not five times


async def test_multi_page_ocr_joins_pages_with_blank_lines():
    def fake_convert(_data, **kwargs):
        page = kwargs["first_page"]
        return [f"image-{page}"]

    with (
        patch("ucenik.rag.extractor.convert_from_bytes", side_effect=fake_convert),
        patch("ucenik.rag.extractor.pytesseract.image_to_string", side_effect=["First page.", "Second page."]),
    ):
        text = await extract_text("application/pdf", _blank_pdf_bytes(pages=2))

    assert text == "First page.\n\nSecond page."


async def test_ocr_calls_are_scoped_to_a_single_page_each():
    """Each page needing OCR gets its own convert_from_bytes call
    (first_page == last_page) - a large scanned document never has more
    than one page's image in memory at a time, unlike rendering a range.
    """

    def fake_convert(_data, **kwargs):
        return [f"page-{kwargs['first_page']}"]

    with (
        patch("ucenik.rag.extractor.convert_from_bytes", side_effect=fake_convert) as mock_convert,
        patch("ucenik.rag.extractor.pytesseract.image_to_string", side_effect=lambda img: f"[{img}]"),
    ):
        text = await extract_text("application/pdf", _blank_pdf_bytes(pages=4))

    calls = [(c.kwargs["first_page"], c.kwargs["last_page"]) for c in mock_convert.call_args_list]
    assert calls == [(1, 1), (2, 2), (3, 3), (4, 4)]
    assert "[page-1]" in text
    assert "[page-4]" in text


async def test_mixed_document_only_ocrs_pages_without_native_text():
    """The core scenario: page 1 has a real text layer, page 2 doesn't -
    OCR should run for page 2 only, and page 1's native text should pass
    through completely untouched.
    """
    fake_reader = _fake_reader(["Real native text on page one.", ""])

    with (
        patch("ucenik.rag.extractor.PdfReader", return_value=fake_reader),
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]) as mock_convert,
        patch("ucenik.rag.extractor.pytesseract.image_to_string", return_value="Recovered via OCR."),
    ):
        text = await extract_text("application/pdf", b"irrelevant - PdfReader is mocked")

    assert text == "Real native text on page one.\n\nRecovered via OCR."
    # only page 2 (the one with no native text) was ever rendered for OCR
    mock_convert.assert_called_once_with(
        b"irrelevant - PdfReader is mocked", dpi=300, first_page=2, last_page=2, grayscale=True
    )


async def test_corrupt_page_does_not_take_down_the_whole_document():
    """A page whose extract_text() raises outright (not just returns empty)
    is treated the same as a page with no text layer - sent to OCR - rather
    than crashing extraction for every other page in the document.
    """
    fake_reader = _fake_reader([None, "Fine page after the corrupt one."])

    with (
        patch("ucenik.rag.extractor.PdfReader", return_value=fake_reader),
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]),
        patch("ucenik.rag.extractor.pytesseract.image_to_string", return_value="Recovered corrupt page."),
    ):
        text = await extract_text("application/pdf", b"irrelevant")

    assert text == "Recovered corrupt page.\n\nFine page after the corrupt one."


async def test_broken_page_is_skipped_when_another_page_has_content():
    """One page has real text, another has neither a native text layer nor
    anything OCR can recover (genuinely blank/broken) - the document still
    succeeds using whatever content actually exists, rather than failing
    the whole document over one bad page.
    """
    fake_reader = _fake_reader(["The only real content in this document.", ""])

    with (
        patch("ucenik.rag.extractor.PdfReader", return_value=fake_reader),
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]),
        patch("ucenik.rag.extractor.pytesseract.image_to_string", return_value="   "),  # OCR also finds nothing
    ):
        text = await extract_text("application/pdf", b"irrelevant")

    assert text == "The only real content in this document."


async def test_pua_glyph_page_falls_back_to_ocr_and_prefers_it():
    """A page whose native text isn't empty but contains Private Use Area
    codepoints (a symbol-font-mapped formula, e.g. an old Word Equation
    Editor / MathType PDF - see _has_pua_glyphs) should still trigger OCR,
    and the OCR result should win over the PUA-corrupted native text.
    """
    fake_reader = _fake_reader([f"p {_PUA_GLYPH} q {_PUA_GLYPH} r", "A normal page with no symbols."])

    with (
        patch("ucenik.rag.extractor.PdfReader", return_value=fake_reader),
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]) as mock_convert,
        patch("ucenik.rag.extractor.pytesseract.image_to_string", return_value="p ∧ q → r"),
    ):
        text = await extract_text("application/pdf", b"irrelevant")

    assert text == "p ∧ q → r\n\nA normal page with no symbols."
    # only the PUA-glyph page (page 1) was sent to OCR, the clean page wasn't
    mock_convert.assert_called_once_with(b"irrelevant", dpi=300, first_page=1, last_page=1, grayscale=True)


async def test_pua_glyph_page_keeps_native_text_when_ocr_finds_nothing():
    """OCR failing to recover anything for a PUA-glyph page shouldn't
    discard the native text that IS there (real prose around the
    corrupted symbols) - degraded beats empty.
    """
    fake_reader = _fake_reader([f"Ispitati formulu: p {_PUA_GLYPH} q {_PUA_GLYPH} r"])

    with (
        patch("ucenik.rag.extractor.PdfReader", return_value=fake_reader),
        patch("ucenik.rag.extractor.convert_from_bytes", return_value=["fake-image"]),
        patch("ucenik.rag.extractor.pytesseract.image_to_string", return_value="   "),
    ):
        text = await extract_text("application/pdf", b"irrelevant")

    assert text == f"Ispitati formulu: p {_PUA_GLYPH} q {_PUA_GLYPH} r"


# --- Structure: heading paths per format -----------------------------------


class _Bookmark:
    """pypdf outline entries only need a .title for _pdf_outline_starts."""

    def __init__(self, title: str):
        self.title = title


def _reader_with_outline(page_texts: list[str], outline: list, start_pages: dict[str, int]) -> MagicMock:
    reader = _fake_reader(page_texts)
    reader.outline = outline
    reader.get_destination_page_number.side_effect = lambda bookmark: start_pages[bookmark.title]
    return reader


async def test_pdf_bookmarks_become_nested_heading_paths():
    reader = _reader_with_outline(
        ["Preface text.", "Cells divide.", "Mitosis has four stages.", "Plants make food."],
        [_Bookmark("Chapter 1: Cells"), [_Bookmark("Mitosis")], _Bookmark("Chapter 2: Plants")],
        {"Chapter 1: Cells": 1, "Mitosis": 2, "Chapter 2: Plants": 3},
    )
    with patch("ucenik.rag.extractor.PdfReader", return_value=reader):
        sections = await extract_sections("application/pdf", b"irrelevant - PdfReader is mocked")

    assert [s.heading_path for s in sections] == [
        [],  # before the first bookmark
        ["Chapter 1: Cells"],
        ["Chapter 1: Cells", "Mitosis"],
        ["Chapter 2: Plants"],
    ]
    assert sections[2].text == "Mitosis has four stages."


async def test_pdf_consecutive_pages_under_one_bookmark_merge_into_one_section():
    reader = _reader_with_outline(["Page one.", "Page two."], [_Bookmark("Chapter 1")], {"Chapter 1": 0})
    with patch("ucenik.rag.extractor.PdfReader", return_value=reader):
        sections = await extract_sections("application/pdf", b"irrelevant")

    assert sections == [Section(heading_path=["Chapter 1"], text="Page one.\n\nPage two.")]


async def test_pdf_unreadable_outline_is_not_fatal():
    from unittest.mock import PropertyMock

    reader = _fake_reader(["Some text."])
    type(reader).outline = PropertyMock(side_effect=RuntimeError("broken outline"))
    with patch("ucenik.rag.extractor.PdfReader", return_value=reader):
        sections = await extract_sections("application/pdf", b"irrelevant")

    assert sections == [Section(heading_path=[], text="Some text.")]


async def test_docx_heading_styles_become_heading_paths_and_tables_stay_in_their_section():
    from docx import Document

    doc = Document()
    doc.add_heading("Biology", 0)  # "Title" style
    doc.add_heading("Cells", 1)
    doc.add_paragraph("Cells are the basic unit of life.")
    doc.add_heading("Mitosis", 2)
    doc.add_paragraph("Mitosis has four stages.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "First stage"
    table.cell(0, 1).text = "Prophase"
    doc.add_heading("Plants", 1)  # back up a level: replaces Cells > Mitosis
    doc.add_paragraph("Plants photosynthesize.")
    buf = io.BytesIO()
    doc.save(buf)

    sections = await extract_sections(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buf.getvalue()
    )

    assert [s.heading_path for s in sections] == [
        ["Biology"],
        ["Biology", "Cells"],
        ["Biology", "Cells", "Mitosis"],
        ["Biology", "Plants"],
    ]
    assert "Mitosis has four stages." in sections[2].text
    assert "First stage | Prophase" in sections[2].text


async def test_pptx_slides_are_sections_headed_by_their_titles():
    from pptx import Presentation
    from pptx.util import Inches

    pres = Presentation()
    titled = pres.slides.add_slide(pres.slide_layouts[1])  # title + content
    titled.shapes.title.text = "Mitosis"
    titled.placeholders[1].text = "Four stages."
    untitled = pres.slides.add_slide(pres.slide_layouts[6])  # blank, no title placeholder
    untitled.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text_frame.text = "A diagram caption."
    buf = io.BytesIO()
    pres.save(buf)

    sections = await extract_sections(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", buf.getvalue()
    )

    assert [s.heading_path for s in sections] == [["Slide 1: Mitosis"], ["Slide 2"]]
    assert "Four stages." in sections[0].text


async def test_xlsx_sheets_are_sections_headed_by_their_names():
    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.active.title = "Grades"
    workbook.active.append(["Ana", 5])
    workbook.create_sheet("Schedule").append(["Monday", "Biology"])
    buf = io.BytesIO()
    workbook.save(buf)

    sections = await extract_sections(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buf.getvalue()
    )

    assert sections == [
        Section(heading_path=["Grades"], text="Ana | 5"),
        Section(heading_path=["Schedule"], text="Monday | Biology"),
    ]


def test_render_sections_labels_headed_sections_only():
    rendered = render_sections([Section([], "Preface."), Section(["Ch 1", "Cells"], "Cells divide.")])
    assert rendered == "Preface.\n\n[Ch 1 > Cells]\nCells divide."
