"""Document upload/list/download/delete + the ingest-dispatch decision -
see api/documents.py for the request/response shapes. Ingest itself
(rag/ingest.py) runs as a FastAPI BackgroundTask, not inline - see
docs/rag-notes.md.
"""

import hashlib
import re

from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError

from ucenik.cache.chat_cache import bump_subject_version
from ucenik.core.storage import delete_file, download_file, file_exists, upload_file
from ucenik.errors.persistence import translate_duplicate_key
from ucenik.errors.service import DuplicateResourceError, PayloadTooLargeError, UnsupportedMediaTypeError
from ucenik.models.documents import Document
from ucenik.models.subjects import Subject
from ucenik.rag.ingest import ingest_document
from ucenik.rag.vector_store import delete_document_chunks

# Office Open XML only (.docx/.pptx/.xlsx) - not legacy binary .doc/.ppt/.xls,
# see rag/extractor.py.
ALLOWED_CONTENT_TYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Filenames are attacker-controlled (whatever the browser sends). Not a
# backend XSS risk by itself - responses are JSON, never rendered as HTML
# here - but defense in depth: a naive frontend that renders a filename
# unescaped shouldn't get bitten by one containing "<script>" etc. Also
# strips path separators, since this string is never used as a real
# filesystem path (storage is content-addressed by hash, not by name -
# see core/storage.py) but there's no reason to keep them around either.
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_filename(filename: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", filename).strip()
    return cleaned[:255] or "unnamed"


async def upload_document(
    subject: Subject,
    uploaded_by: str,
    filename: str | None,
    content_type: str | None,
    data: bytes,
) -> tuple[Document, bool]:
    """Returns (document, is_new) - `is_new` is False for the dedup no-op
    case (identical content already ingested/in-progress for this subject),
    so the caller only dispatches ingest for content that actually needs it.
    """
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError(f"unsupported content type: {content_type}")

    if len(data) > MAX_FILE_SIZE:
        raise PayloadTooLargeError(f"file exceeds the {MAX_FILE_SIZE} byte limit")

    file_hash = hashlib.sha256(data).hexdigest()

    # dedup: identical content already ingested (or in progress) for this
    # subject - no-op, just hand back the existing record.
    existing = await Document.find_one(Document.subject_id == str(subject.id), Document.file_hash == file_hash)
    if existing is not None:
        return existing, False

    if not await file_exists(file_hash):
        await upload_file(file_hash, data, content_type=content_type)

    document = Document(
        subject_id=str(subject.id),
        filename=_sanitize_filename(filename or "unnamed"),
        content_type=content_type,
        file_hash=file_hash,
        uploaded_by=uploaded_by,
    )
    try:
        await document.insert()
    except MongoDuplicateKeyError as exc:
        # race: two concurrent uploads of the same file beat us to it
        existing = await Document.find_one(Document.subject_id == str(subject.id), Document.file_hash == file_hash)
        if existing is not None:
            return existing, False
        raise DuplicateResourceError("Document", file_hash) from translate_duplicate_key("Document", exc)

    return document, True


async def list_documents(subject: Subject) -> list[Document]:
    return await Document.find(Document.subject_id == str(subject.id)).to_list()


async def get_document_bytes(document: Document) -> bytes:
    """Raw bytes, available regardless of ingest status - upload_document()
    writes the raw object to storage synchronously, before the Document row
    even exists, so it's there whether ingest is still pending or failed
    outright; ingest status only gates whether the document is *searchable*
    (RAG-wise), not whether the original file exists.
    """
    return await download_file(document.file_hash)


async def delete_document(document: Document) -> None:
    await delete_document_chunks(document.subject_id, str(document.id))
    await bump_subject_version(document.subject_id)  # invalidate cached Tutor answers - see cache/chat_cache.py
    file_hash = document.file_hash
    await document.delete()

    # only delete the S3 object if no other Document (any subject) still
    # references this content hash - see core/storage.py
    remaining = await Document.find_one(Document.file_hash == file_hash)
    if remaining is None:
        await delete_file(file_hash)


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "MAX_FILE_SIZE",
    "upload_document",
    "list_documents",
    "get_document_bytes",
    "delete_document",
    "ingest_document",
]
