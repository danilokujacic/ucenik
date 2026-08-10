"""Redis cache for Tutor answers (docs/backlog.md item 8) - skips retrieval
+ generation entirely for a question that's already been asked and answered
in the same subject.

Scope, deliberately narrow: only the FIRST question in a session is a
caching candidate (see api/chat.py's ask_question). Once there's any
conversation history, the "same" question text can mean something
different depending on what came before it (follow-ups, corrections,
"actually, what about..."), so honoring the cache there risks serving a
stale/wrong answer just because a similarly-worded first question happened
to be asked once before. A first question has no such ambiguity - it's
genuinely the same question, in the same subject, with nothing preceding it
to change what it means. This also keeps a hit free of charge: since a
cache hit skips the LLM call entirely, api/chat.py skips check_quota() for
it too (see its docstring) - a student who's out of quota can still get an
answer that's already been paid for once.

Invalidation: every cached entry is stamped with the subject's current
"content version", an integer bumped once on every successful ingest
(rag/ingest.py) and every document delete (api/documents.py) - anything
that changes what's retrievable for the subject. A read compares its stored
version against the subject's current version and treats a mismatch as a
miss, so re-ingesting or removing a document invalidates every cached
answer for that subject in O(1) without enumerating or deleting individual
answer keys.
"""

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel

from ucenik.core.redis import get_redis

_ANSWER_TTL_SECONDS = (
    60 * 60 * 24 * 7
)  # 7 days - long enough to pay off repeat questions, short enough not to fossilize


class CachedAnswer(BaseModel):
    content: str
    sources: list[dict]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_at: datetime


def _version_key(subject_id: str) -> str:
    return f"chat_cache:version:{subject_id}"


def _answer_key(subject_id: str, version: int, question: str) -> str:
    # Normalized so "What is mitosis?" and "what is mitosis?  " share a
    # cache entry - the LLM's answer wouldn't meaningfully differ either way.
    normalized = " ".join(question.strip().lower().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"chat_cache:answer:{subject_id}:{version}:{digest}"


async def _current_version(subject_id: str) -> int:
    raw = await get_redis().get(_version_key(subject_id))
    return int(raw) if raw is not None else 1


async def bump_subject_version(subject_id: str) -> None:
    """Call on anything that changes a subject's retrievable content -
    successful ingest, document delete. INCR rather than deleting individual
    answer keys: O(1) and needs no tracking of which keys currently exist.
    """
    await get_redis().incr(_version_key(subject_id))


async def get_cached_answer(subject_id: str, question: str) -> CachedAnswer | None:
    version = await _current_version(subject_id)
    raw = await get_redis().get(_answer_key(subject_id, version, question))
    if raw is None:
        return None
    return CachedAnswer.model_validate_json(raw)


async def set_cached_answer(
    subject_id: str,
    question: str,
    *,
    content: str,
    sources: list[dict],
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    version = await _current_version(subject_id)
    answer = CachedAnswer(
        content=content,
        sources=sources,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cached_at=datetime.now(UTC),
    )
    await get_redis().set(_answer_key(subject_id, version, question), answer.model_dump_json(), ex=_ANSWER_TTL_SECONDS)
