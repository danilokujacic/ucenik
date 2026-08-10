from datetime import UTC, datetime
from enum import Enum

from beanie import Document, Indexed
from pydantic import Field


class LectureStatus(str, Enum):
    PENDING = "pending"  # created, generation not started/queued
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class Lecture(Document):
    """One lecture within a Plan. Content itself lives in LectureVersion
    (models/lecture_versions.py) - a Lecture is the stable identity +
    current status, `current_version` points at which LectureVersion is
    "live". Never deleted on refine/rollback - see lecture_versions.py.
    """

    plan_id: Indexed(str)
    # Denormalized from Plan.subject_id - same reasoning as Document.subject_id
    # (models/documents.py): avoids a Plan lookup on every permission check.
    subject_id: Indexed(str)
    created_by: str  # quota attribution (core/quota.py) for generate/refine LLM calls
    order: int
    title: str
    topic: str  # what the teacher wants this lecture to cover - the generation prompt input

    status: LectureStatus = LectureStatus.PENDING
    error: str | None = None
    current_version: int = 0  # 0 = no version generated yet

    # Remembers the last refine() call's parameters so a failed refine can
    # be retried blindly (POST .../retry, api/lectures.py) without the
    # caller having to re-specify the transform. Unset for a lecture that's
    # never had a refine attempt.
    last_refine_transform: str | None = None
    last_refine_target_language: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "lectures"
