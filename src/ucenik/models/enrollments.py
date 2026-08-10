from datetime import UTC, datetime

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class Enrollment(Document):
    subject_id: str
    student_id: str
    enrolled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "enrollments"
        indexes = [
            IndexModel([("subject_id", 1), ("student_id", 1)], unique=True),
        ]
