"""Tutor chat routes - see services/chat.py for the RAG query flow, SSE
event generation, and quota/cache logic. Answers stream back over SSE
(Server-Sent Events) so the UI can show tokens as they're generated instead
of waiting for the whole answer - see rag-notes.md's "Streaming (SSE)"
section.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ucenik.core.permissions import require_subject_access
from ucenik.core.security import get_current_user
from ucenik.models.chat_messages import ChatMessage, MessageRole, SourceRef
from ucenik.models.chat_sessions import ChatSession
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.services import chat as chat_service
from ucenik.services.chat import get_own_chat_session

router = APIRouter(prefix="/subjects/{subject_id}/chat/sessions", tags=["chat"])


class ChatSessionPublic(BaseModel):
    id: str
    subject_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessagePublic(BaseModel):
    id: str
    role: MessageRole
    content: str
    sources: list[SourceRef]
    created_at: datetime


class AskQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


def _session_to_public(session: ChatSession) -> ChatSessionPublic:
    return ChatSessionPublic(
        id=str(session.id),
        subject_id=session.subject_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _message_to_public(message: ChatMessage) -> ChatMessagePublic:
    return ChatMessagePublic(
        id=str(message.id),
        role=message.role,
        content=message.content,
        sources=message.sources,
        created_at=message.created_at,
    )


@router.post("", response_model=ChatSessionPublic, status_code=status.HTTP_201_CREATED)
async def create_session(
    subject: Annotated[Subject, Depends(require_subject_access)],
    user: Annotated[User, Depends(get_current_user)],
) -> ChatSessionPublic:
    session = await chat_service.create_session(subject, user)
    return _session_to_public(session)


@router.get("", response_model=list[ChatSessionPublic])
async def list_sessions(
    subject: Annotated[Subject, Depends(require_subject_access)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[ChatSessionPublic]:
    sessions = await chat_service.list_sessions(subject, user)
    return [_session_to_public(s) for s in sessions]


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session: Annotated[ChatSession, Depends(get_own_chat_session)]) -> None:
    await chat_service.delete_session(session)


@router.get("/{session_id}/messages", response_model=list[ChatMessagePublic])
async def list_messages(session: Annotated[ChatSession, Depends(get_own_chat_session)]) -> list[ChatMessagePublic]:
    messages = await chat_service.list_messages(session)
    return [_message_to_public(m) for m in messages]


@router.post("/{session_id}/title", response_model=ChatSessionPublic)
async def generate_title(
    session: Annotated[ChatSession, Depends(get_own_chat_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> ChatSessionPublic:
    session = await chat_service.generate_session_title(session, user)
    return _session_to_public(session)


@router.post("/{session_id}/messages")
async def ask_question(
    payload: AskQuestionRequest,
    session: Annotated[ChatSession, Depends(get_own_chat_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    stream = await chat_service.prepare_answer_stream(session, user, payload.question)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
