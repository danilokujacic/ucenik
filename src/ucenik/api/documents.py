"""Document upload + management. Upload kicks off the ingest pipeline
(rag/ingest.py) as a background task, not inline - see docs/rag-notes.md.
"""

import hashlib
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, status
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError

from ucenik.core.permissions import get_document, require_subject_access, require_subject_owner
from ucenik.core.security import get_current_user
from ucenik.core.storage import delete_file, file_exists, upload_file
from ucenik.errors.persistence import translate_duplicate_key
from ucenik.errors.service import DuplicateResourceError, PayloadTooLargeError, UnsupportedMediaTypeError
from ucenik.models.documents import Document, DocumentStatus
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.rag.ingest import ingest_document
from ucenik.rag.vector_store import delete_document_chunks

router = APIRouter(prefix="/subjects/{subject_id}/documents", tags=["documents"])

_ALLOWED_CONTENT_TYPES = {"text/plain", "application/pdf"}
_MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


class DocumentPublic(BaseModel):
    id: str
    filename: str
    content_type: str
    status: DocumentStatus
    error: str | None
    chunk_count: int


def _to_public(document: Document) -> DocumentPublic:
    return DocumentPublic(
        id=str(document.id),
        filename=document.filename,
        content_type=document.content_type,
        status=document.status,
        error=document.error,
        chunk_count=document.chunk_count,
    )


@router.post("", response_model=DocumentPublic, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    subject: Annotated[Subject, Depends(require_subject_owner)],
    user: Annotated[User, Depends(get_current_user)],
) -> DocumentPublic:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise UnsupportedMediaTypeError(f"unsupported content type: {file.content_type}")

    data = await file.read()
    if len(data) > _MAX_FILE_SIZE:
        raise PayloadTooLargeError(f"file exceeds the {_MAX_FILE_SIZE} byte limit")

    file_hash = hashlib.sha256(data).hexdigest()

    # dedup: identical content already ingested (or in progress) for this
    # subject - no-op, just hand back the existing record.
    existing = await Document.find_one(Document.subject_id == str(subject.id), Document.file_hash == file_hash)
    if existing is not None:
        return _to_public(existing)

    if not await file_exists(file_hash):
        await upload_file(file_hash, data, content_type=file.content_type)

    document = Document(
        subject_id=str(subject.id),
        filename=file.filename or "unnamed",
        content_type=file.content_type,
        file_hash=file_hash,
        uploaded_by=str(user.id),
    )
    try:
        await document.insert()
    except MongoDuplicateKeyError as exc:
        # race: two concurrent uploads of the same file beat us to it
        existing = await Document.find_one(Document.subject_id == str(subject.id), Document.file_hash == file_hash)
        if existing is not None:
            return _to_public(existing)
        raise DuplicateResourceError("Document", file_hash) from translate_duplicate_key("Document", exc)

    background_tasks.add_task(ingest_document, str(document.id))

    return _to_public(document)


@router.get("", response_model=list[DocumentPublic])
async def list_documents(subject: Annotated[Subject, Depends(require_subject_access)]) -> list[DocumentPublic]:
    documents = await Document.find(Document.subject_id == str(subject.id)).to_list()
    return [_to_public(d) for d in documents]


@router.get("/{document_id}", response_model=DocumentPublic)
async def get_document_details(
    document: Annotated[Document, Depends(get_document)],
    _subject: Annotated[Subject, Depends(require_subject_access)],
) -> DocumentPublic:
    return _to_public(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document: Annotated[Document, Depends(get_document)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> None:
    await delete_document_chunks(document.subject_id, str(document.id))
    file_hash = document.file_hash
    await document.delete()

    # only delete the S3 object if no other Document (any subject) still
    # references this content hash - see core/storage.py
    remaining = await Document.find_one(Document.file_hash == file_hash)
    if remaining is None:
        await delete_file(file_hash)
