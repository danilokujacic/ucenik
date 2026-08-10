from datetime import UTC, datetime

from beanie import Document, Indexed
from pydantic import Field


class Plan(Document):
    """A teacher's lecture plan for a subject - an ordered container of
    Lectures (models/lectures.py). Ownership is derived from the subject it
    belongs to (only the owning teacher/admin can manage it, same rule as
    documents), not stored independently - see core/permissions.py.
    """

    subject_id: Indexed(str)
    teacher_id: str  # creator, for audit - not itself an authorization source
    title: str
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "plans"
