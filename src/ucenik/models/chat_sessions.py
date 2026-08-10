from datetime import UTC, datetime

from beanie import Document, Indexed
from pydantic import Field


class ChatSession(Document):
    """One Tutor conversation thread. Private to the student/teacher who
    started it - see api/chat.py's permission checks. `title` defaults to
    the first question asked (truncated), purely for a UI session-list
    label, and can be overwritten with a nicer LLM-generated one via POST
    .../title - see services/chat.generate_session_title.
    """

    subject_id: Indexed(str)
    user_id: Indexed(str)
    title: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "chat_sessions"
