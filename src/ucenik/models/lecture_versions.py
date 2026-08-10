from datetime import UTC, datetime
from enum import Enum

from beanie import Document, Indexed
from pydantic import Field
from pymongo import IndexModel


class VersionSource(str, Enum):
    AI_GENERATED = "ai_generated"  # first version, from Lecture.topic + retrieved context
    AI_REFINED = "ai_refined"  # shorten/extend/regenerate/translate - see rag/refiner.py
    MANUAL_EDIT = "manual_edit"  # teacher edited the content directly, no LLM call
    ROLLBACK = "rollback"  # a copy of an older version, made current again


class LectureVersion(Document):
    """Full version history for a Lecture - versions are never deleted or
    overwritten, only appended to (§Phase 7 "versioning"). Rolling back
    creates a *new* version copying an old one's content rather than
    un-deleting anything, so the history stays a complete, honest audit
    trail of everything that happened to a lecture.
    """

    lecture_id: Indexed(str)
    version: int  # 1, 2, 3, ... monotonically increasing per lecture
    content: str  # markdown, with LaTeX ($.../$$...$$) and TikZ/SVG code blocks - see rag/refiner.py
    source: VersionSource
    change_summary: str | None = None  # e.g. "shortened", "translated to French", "manual edit"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "lecture_versions"
        indexes = [
            IndexModel([("lecture_id", 1), ("version", 1)], unique=True),
        ]
