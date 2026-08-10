from datetime import UTC, datetime
from enum import Enum

from beanie import Document, Indexed
from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class SourceRef(BaseModel):
    """Not its own Beanie collection - embedded inline in ChatMessage below
    (see `sources`). Plain pydantic model, not a Document: it has no
    identity/collection of its own, it's just a typed shape nested in a
    ChatMessage's `sources` list.
    """

    document_id: str
    source_filename: str


class ChatMessage(Document):
    session_id: Indexed(str)
    role: MessageRole
    content: str

    # Populated on assistant messages only: which chunks the answer was
    # grounded in (empty list = nothing relevant was retrieved, the honest
    # "I don't know" case - see rag/generator.py), and token usage for the
    # quota system (core/quota.py).
    sources: list[SourceRef] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    class Settings:
        name = "chat_messages"
