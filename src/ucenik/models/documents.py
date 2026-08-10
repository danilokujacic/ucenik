from datetime import UTC, datetime
from enum import Enum

from beanie import Document as BeanieDocument
from beanie import Indexed
from pydantic import Field
from pymongo import IndexModel


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(BeanieDocument):
    subject_id: Indexed(str)
    filename: str
    content_type: str
    # Content hash of the raw bytes - also the S3 key (core/storage.py). Not
    # globally unique here on purpose: the same file content can be uploaded
    # to more than one subject, each getting its own Document row (and its
    # own chunks/embeddings in that subject's Chroma collection), while
    # sharing one underlying S3 object.
    file_hash: str

    status: DocumentStatus = DocumentStatus.PENDING
    error: str | None = None
    chunk_count: int = 0
    uploaded_by: str

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "documents"
        indexes = [
            # dedup scope: re-uploading identical content to a subject that
            # already ingested it should be a no-op, not a duplicate Document
            IndexModel([("subject_id", 1), ("file_hash", 1)], unique=True),
        ]
