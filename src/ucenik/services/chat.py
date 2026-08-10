"""Tutor chat - the RAG query flow (§Phase 5, docs/rag-notes.md). See
api/chat.py for the request/response shapes and SSE framing note.

Sessions are private: only the user who started a session can read or post
to it. Unlike subjects/documents, there is no admin/teacher bypass here on
purpose - a Tutor conversation is closer to a private tutoring session than
shared course content, and nothing in the spec calls for oversight access.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends

from ucenik.cache.chat_cache import CachedAnswer, get_cached_answer, set_cached_answer
from ucenik.core.permissions import require_subject_access
from ucenik.core.quota import check_quota, record_usage
from ucenik.core.security import get_current_user
from ucenik.errors.service import ExternalServiceUnavailableError, InvalidStateError, NotFoundError, parse_object_id
from ucenik.llm.proxy_client import LLMProxyError
from ucenik.models.chat_messages import ChatMessage, MessageRole, SourceRef
from ucenik.models.chat_sessions import ChatSession
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.rag.generator import stream_answer
from ucenik.rag.retriever import RetrievedChunk, retrieve
from ucenik.rag.titler import generate_title

logger = logging.getLogger(__name__)

# How many prior turns (user+assistant messages) get replayed into the
# prompt as conversation history. Capped so a long-running session doesn't
# grow the prompt unboundedly - see rag-notes.md's chunking notes on the
# generation prompt budget (chunk size x k, alongside history, has to fit).
_MAX_HISTORY_MESSAGES = 20

_TITLE_MAX_LENGTH = 80


async def get_own_chat_session(
    subject_id: str,
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    _subject: Annotated[Subject, Depends(require_subject_access)],
) -> ChatSession:
    session = await ChatSession.get(parse_object_id("ChatSession", session_id))
    if session is None or session.subject_id != subject_id or session.user_id != str(user.id):
        # Same id, wrong subject, or someone else's session all look
        # identical to the caller - existence isn't leaked outside the owner.
        raise NotFoundError("ChatSession", session_id)
    return session


async def create_session(subject: Subject, user: User) -> ChatSession:
    session = ChatSession(subject_id=str(subject.id), user_id=str(user.id))
    await session.insert()
    return session


async def list_sessions(subject: Subject, user: User) -> list[ChatSession]:
    return (
        await ChatSession.find(ChatSession.subject_id == str(subject.id), ChatSession.user_id == str(user.id))
        .sort(-ChatSession.updated_at)
        .to_list()
    )


async def delete_session(session: ChatSession) -> None:
    await ChatMessage.find(ChatMessage.session_id == str(session.id)).delete()
    await session.delete()


async def list_messages(session: ChatSession) -> list[ChatMessage]:
    return await ChatMessage.find(ChatMessage.session_id == str(session.id)).sort(+ChatMessage.created_at).to_list()


async def generate_session_title(session: ChatSession, user: User) -> ChatSession:
    """LLM-generated one-line title from the session's first question,
    replacing the truncated-question fallback set automatically in
    _stream_answer_events. A separate action (not automatic) so a title
    only costs an LLM call - and quota - when a caller actually wants one,
    not on every session's first message.
    """
    first_message = (
        await ChatMessage.find(ChatMessage.session_id == str(session.id), ChatMessage.role == MessageRole.USER)
        .sort(+ChatMessage.created_at)
        .first_or_none()
    )
    if first_message is None:
        raise InvalidStateError("cannot generate a title before the first question is asked")

    await check_quota(str(user.id))

    try:
        result = await generate_title(first_message.content)
    except LLMProxyError as exc:
        logger.warning(
            "chat.title_generation_failed",
            extra={"event": "chat.title_generation_failed", "session_id": str(session.id), "error": str(exc)},
        )
        raise ExternalServiceUnavailableError("title generation is temporarily unavailable, please try again") from exc

    await record_usage(str(user.id), result.total_tokens)

    title = result.content.strip().strip("\"'")
    session.title = title[:_TITLE_MAX_LENGTH] if title else first_message.content[:_TITLE_MAX_LENGTH]
    session.updated_at = datetime.now(UTC)
    await session.save()
    return session


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _unique_sources(chunks: list[RetrievedChunk]) -> list[SourceRef]:
    """One SourceRef per document_id, not one per chunk - retrieval can (and
    often does) return several chunks from the same document, and citing it
    that many times would just be repetitive noise in the UI. Keeps
    retrieval-rank order: the first (best-ranked) chunk from a document
    decides where it lands in the list.
    """
    seen: dict[str, SourceRef] = {}
    for chunk in chunks:
        if chunk.document_id not in seen:
            seen[chunk.document_id] = SourceRef(document_id=chunk.document_id, source_filename=chunk.source_filename)
    return list(seen.values())


async def _stream_answer_events(
    session: ChatSession,
    user_id: str,
    question: str,
    cached: CachedAnswer | None,
    cacheable: bool,
) -> AsyncIterator[str]:
    history_messages = (
        await ChatMessage.find(ChatMessage.session_id == str(session.id))
        .sort(-ChatMessage.created_at)
        .limit(_MAX_HISTORY_MESSAGES)
        .to_list()
    )
    history = [{"role": m.role.value, "content": m.content} for m in reversed(history_messages)]

    await ChatMessage(session_id=str(session.id), role=MessageRole.USER, content=question).insert()
    if session.title is None:
        session.title = question[:_TITLE_MAX_LENGTH]
    session.updated_at = datetime.now(UTC)
    await session.save()

    if cached is not None:
        # No retrieval, no LLM call, no quota consumed (see prepare_answer_stream) -
        # replay the previously-generated answer verbatim.
        sources = [SourceRef(**s) for s in cached.sources]
        yield _sse("token", {"content": cached.content})

        message = await ChatMessage(
            session_id=str(session.id),
            role=MessageRole.ASSISTANT,
            content=cached.content,
            sources=sources,
            prompt_tokens=cached.prompt_tokens,
            completion_tokens=cached.completion_tokens,
            total_tokens=cached.total_tokens,
        ).insert()
        session.updated_at = datetime.now(UTC)
        await session.save()

        yield _sse(
            "done",
            {
                "message_id": str(message.id),
                "sources": [s.model_dump() for s in sources],
                "usage": {
                    "prompt_tokens": message.prompt_tokens,
                    "completion_tokens": message.completion_tokens,
                    "total_tokens": message.total_tokens,
                },
                "cached": True,
            },
        )
        return

    chunks = await retrieve(session.subject_id, question)
    sources = _unique_sources(chunks)

    try:
        stream = await stream_answer(chunks, history, question)
        content = ""
        async for delta in stream:
            content += delta
            yield _sse("token", {"content": delta})
    except LLMProxyError as exc:
        # Honest failure (rag-notes.md): tell the client generation failed
        # rather than silently closing the stream or fabricating an answer.
        # No assistant message is persisted - nothing coherent to save, and
        # the user's question is still there in history for a retry.
        logger.warning("chat.generation_failed", extra={"event": "chat.generation_failed", "error": str(exc)})
        yield _sse("error", {"detail": "the Tutor is temporarily unavailable, please try again"})
        return

    usage = stream.usage
    total_tokens = usage.total_tokens if usage else 0
    await record_usage(user_id, total_tokens)

    message = await ChatMessage(
        session_id=str(session.id),
        role=MessageRole.ASSISTANT,
        content=content,
        sources=sources,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        total_tokens=total_tokens,
    ).insert()
    session.updated_at = datetime.now(UTC)
    await session.save()

    if cacheable:
        await set_cached_answer(
            session.subject_id,
            question,
            content=content,
            sources=[s.model_dump() for s in sources],
            prompt_tokens=message.prompt_tokens,
            completion_tokens=message.completion_tokens,
            total_tokens=total_tokens,
        )

    yield _sse(
        "done",
        {
            "message_id": str(message.id),
            "sources": [s.model_dump() for s in sources],
            "usage": {
                "prompt_tokens": message.prompt_tokens,
                "completion_tokens": message.completion_tokens,
                "total_tokens": total_tokens,
            },
            "cached": False,
        },
    )


async def prepare_answer_stream(session: ChatSession, user: User, question: str) -> AsyncIterator[str]:
    """Checks quota *before* returning the generator, so a quota breach is a
    normal 429 JSON response via the global error handler, not something
    smuggled into an SSE event after headers are already sent with a 200 -
    the caller must await this (not just call it) before wrapping the
    result in a StreamingResponse.
    """
    # Only a session's first question is a cache candidate - see
    # cache/chat_cache.py's docstring for why history disqualifies it.
    cacheable = await ChatMessage.find(ChatMessage.session_id == str(session.id)).count() == 0
    cached = await get_cached_answer(session.subject_id, question) if cacheable else None

    if cached is None:
        # Skipped entirely on a cache hit: no LLM call means nothing to
        # charge for.
        await check_quota(str(user.id))

    return _stream_answer_events(session, str(user.id), question, cached, cacheable)
