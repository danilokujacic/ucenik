from datetime import UTC, datetime

from beanie import Document, Indexed
from pydantic import Field


class Subject(Document):
    name: str
    description: str | None = None
    teacher_id: Indexed(str)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "subjects"
