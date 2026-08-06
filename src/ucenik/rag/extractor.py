"""Extracts plain text from an uploaded document's raw bytes.

Format-dependent, but everything downstream (chunking, embedding) is
format-agnostic - this is the one step whose whole job is normalizing messy
real-world files down to one common shape.

Scope for now: plain text and text-layer PDFs (pypdf). Scanned/image-based
PDFs need OCR (pytesseract) to extract anything - deliberately deferred, not
silently unsupported: see docs/rag-notes.md.
"""

import io

from pypdf import PdfReader


class UnsupportedDocumentError(Exception):
    pass


def extract_text(content_type: str, data: bytes) -> str:
    if content_type == "text/plain":
        return data.decode("utf-8", errors="replace")

    if content_type == "application/pdf":
        return _extract_pdf_text(data)

    raise UnsupportedDocumentError(f"unsupported content type: {content_type}")


def _extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(p for p in pages if p.strip())
    if not text.strip():
        raise UnsupportedDocumentError(
            "no extractable text found - likely a scanned/image-based PDF; OCR support not yet implemented"
        )
    return text
