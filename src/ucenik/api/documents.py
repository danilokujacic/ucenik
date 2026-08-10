"""Document upload + management - see services/documents.py for the actual
upload/dedup/storage/ingest-dispatch logic; this file is just the FastAPI
routing, request/response shapes, and BackgroundTasks wiring.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel

from ucenik.core.permissions import get_document, require_subject_access, require_subject_owner
from ucenik.core.security import get_current_user
from ucenik.models.documents import Document, DocumentStatus
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.services import documents as documents_service

router = APIRouter(prefix="/subjects/{subject_id}/documents", tags=["documents"])


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
    data = await file.read()
    document, is_new = await documents_service.upload_document(
        subject, str(user.id), file.filename, file.content_type, data
    )
    if is_new:
        # Module-qualified (not `from ... import ingest_document`) so
        # patching ucenik.services.documents.ingest_document in tests
        # actually takes effect - a bound-at-import-time name wouldn't see
        # a patch applied after this module first loads.
        background_tasks.add_task(documents_service.ingest_document, str(document.id))
    return _to_public(document)


@router.get("", response_model=list[DocumentPublic])
async def list_documents(subject: Annotated[Subject, Depends(require_subject_access)]) -> list[DocumentPublic]:
    documents = await documents_service.list_documents(subject)
    return [_to_public(d) for d in documents]


@router.get("/{document_id}", response_model=DocumentPublic)
async def get_document_details(
    document: Annotated[Document, Depends(get_document)],
    _subject: Annotated[Subject, Depends(require_subject_access)],
) -> DocumentPublic:
    return _to_public(document)


@router.get("/{document_id}/download")
async def download_document(
    document: Annotated[Document, Depends(get_document)],
    _subject: Annotated[Subject, Depends(require_subject_access)],
) -> Response:
    """Same access level as reading the document's metadata
    (require_subject_access) - anyone who can see a document in the list
    can also read its original file (docs/backlog.md item 10).
    """
    data = await documents_service.get_document_bytes(document)
    return Response(
        content=data,
        media_type=document.content_type,
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document: Annotated[Document, Depends(get_document)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> None:
    await documents_service.delete_document(document)
