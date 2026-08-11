"""Planner background jobs (§Phase 6/7): generate a lecture's first version,
or refine an existing one (shorten/extend/regenerate/translate). Each is a
thin Celery task wrapping a plain async function - the async function has
the actual logic and is directly awaitable on its own (same shape as
rag/ingest.py's ingest_document, called by FastAPI BackgroundTasks there);
the Celery task is just `run_async(the_async_function(...))`, dispatched via
`.delay()` from api/lectures.py.

Auto-retry (docs/backlog.md item 7): only `LLMProxyError`/`EmbeddingServiceError`
- transient upstream failures, whether that's the LLM proxy or the embedding
service (retrieve() calls the latter) - get retried, up to `_MAX_RETRIES`
times with backoff. Anything else (QuotaExceededError, a bug, a malformed
lecture) goes straight to `status: failed` with no retry, since retrying
immediately can't fix a quota that's still exceeded or a bug that's still a
bug. The async functions themselves stay the source of truth for "give up
and mark failed" (via `_mark_failed`, called on the final attempt or a
non-retryable exception) - they just *raise* the transient error instead of
swallowing it when a retry attempt remains, and it's the Celery task
wrapper (bind=True, has `self.request.retries`) that turns that raise into
an actual scheduled retry.

Testing note: the test suite calls generate_lecture()/refine_lecture()
directly (`await generate_lecture(...)`), never through `.delay()`.
`task_always_eager` would run the task body synchronously *from inside* the
test's already-running event loop, and workers/celery_app.py's run_async
can't safely nest a second loop inside one that's already running - and even
routing around that via a separate thread wouldn't help, since Motor's
client is bound to a single event loop and can't be used from a different
one. Calling the async function directly sidesteps the whole problem: it
just runs on the test's own loop, no bridging needed at all, identical to
how BackgroundTasks-based ingest is tested. The dispatch call itself
(`generate_lecture_task.delay(...)`) is covered separately by mocking
`.delay` in api-layer tests, confirming the right task+args get queued
without needing a real worker.
"""

import logging

from ucenik.core.pubsub import publish_progress
from ucenik.core.quota import check_quota, record_usage
from ucenik.errors.user_messages import safe_job_error_message
from ucenik.llm.proxy_client import LLMProxyError
from ucenik.models.lecture_versions import LectureVersion, VersionSource
from ucenik.models.lectures import Lecture, LectureStatus
from ucenik.rag.embedder import EmbeddingServiceError
from ucenik.rag.refiner import RefineTransform, generate_lecture_content, refine_lecture_content
from ucenik.rag.retriever import retrieve
from ucenik.workers.celery_app import celery_app, run_async

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3

# Both are "a downstream service this task depends on is transiently
# unreachable" - same retry treatment either way, see module docstring.
_TRANSIENT_ERRORS = (LLMProxyError, EmbeddingServiceError)


async def _next_version_number(lecture_id: str) -> int:
    latest = (
        await LectureVersion.find(LectureVersion.lecture_id == lecture_id).sort(-LectureVersion.version).first_or_none()
    )
    return (latest.version + 1) if latest else 1


async def _mark_failed(lecture: Lecture, exc: Exception) -> None:
    """Stores and publishes the *sanitized* message (safe_job_error_message)
    - not `str(exc)`. Both the DB field (read back through a plain GET) and
    the `lecture.failed` WS event go straight to an end user with no
    request/response cycle left to redact an internal/infra detail at; the
    caller's own logger.exception/logger.warning already captured the real
    exception in full.
    """
    error = safe_job_error_message(exc)
    lecture.status = LectureStatus.FAILED
    lecture.error = error
    await lecture.save()
    await publish_progress(lecture.plan_id, {"type": "lecture.failed", "lecture_id": str(lecture.id), "error": error})


async def generate_lecture(lecture_id: str, attempt: int = 0) -> None:
    lecture = await Lecture.get(lecture_id)
    if lecture is None:
        logger.error("planner.generate: lecture %s not found", lecture_id)
        return

    lecture.status = LectureStatus.GENERATING
    await lecture.save()
    await publish_progress(lecture.plan_id, {"type": "lecture.generating", "lecture_id": str(lecture.id)})

    try:
        # Quota gates retrieval, not just generation - retrieve() calls
        # embed_query(), a real (if smaller) compute cost on
        # embedding_service that a user who's already exhausted their
        # daily quota shouldn't be able to keep triggering for free just
        # by generating more lectures. Mirrors services/chat.py's
        # ask_question flow, which already checks quota before its
        # equivalent retrieve() call ever runs (see prepare_answer_stream's
        # own docstring on why - it checks before the retrieval-calling
        # generator is even constructed).
        await check_quota(lecture.created_by)
        chunks = await retrieve(lecture.subject_id, lecture.topic)
        result = await generate_lecture_content(lecture.topic, chunks)
        await record_usage(lecture.created_by, result.total_tokens)

        await LectureVersion(
            lecture_id=str(lecture.id),
            version=1,
            content=result.content,
            source=VersionSource.AI_GENERATED,
            change_summary="initial generation",
        ).insert()

        lecture.status = LectureStatus.READY
        lecture.current_version = 1
        lecture.error = None
        await lecture.save()
        await publish_progress(lecture.plan_id, {"type": "lecture.ready", "lecture_id": str(lecture.id), "version": 1})
    except _TRANSIENT_ERRORS as exc:
        if attempt < _MAX_RETRIES:
            logger.warning("planner.generate.retrying lecture=%s attempt=%d", lecture_id, attempt + 1)
            await publish_progress(
                lecture.plan_id,
                {
                    "type": "lecture.retrying",
                    "lecture_id": str(lecture.id),
                    "attempt": attempt + 1,
                    "max_attempts": _MAX_RETRIES,
                },
            )
            raise  # let the Celery task wrapper schedule the retry
        logger.exception("planner.generate.failed lecture=%s (retries exhausted)", lecture_id)
        await _mark_failed(lecture, exc)
    except Exception as exc:
        logger.exception("planner.generate.failed lecture=%s", lecture_id)
        await _mark_failed(lecture, exc)


async def refine_lecture(lecture_id: str, transform: str, target_language: str | None = None, attempt: int = 0) -> None:
    lecture = await Lecture.get(lecture_id)
    if lecture is None:
        logger.error("planner.refine: lecture %s not found", lecture_id)
        return

    # Remembered even before the attempt resolves, so a hard failure (no
    # retry budget left) still leaves POST .../retry something to replay -
    # see api/lectures.py's retry endpoint.
    lecture.last_refine_transform = transform
    lecture.last_refine_target_language = target_language
    lecture.status = LectureStatus.GENERATING
    await lecture.save()
    await publish_progress(
        lecture.plan_id, {"type": "lecture.refining", "lecture_id": str(lecture.id), "transform": transform}
    )

    try:
        current = await LectureVersion.find_one(
            LectureVersion.lecture_id == lecture_id, LectureVersion.version == lecture.current_version
        )
        if current is None:
            raise ValueError("no existing version to refine")

        await check_quota(lecture.created_by)
        result = await refine_lecture_content(
            RefineTransform(transform), current.content, target_language=target_language
        )
        await record_usage(lecture.created_by, result.total_tokens)

        next_version = await _next_version_number(lecture_id)
        summary = f"translated to {target_language}" if transform == RefineTransform.TRANSLATE.value else transform
        await LectureVersion(
            lecture_id=lecture_id,
            version=next_version,
            content=result.content,
            source=VersionSource.AI_REFINED,
            change_summary=summary,
        ).insert()

        lecture.status = LectureStatus.READY
        lecture.current_version = next_version
        lecture.error = None
        await lecture.save()
        await publish_progress(
            lecture.plan_id,
            {"type": "lecture.ready", "lecture_id": str(lecture.id), "version": next_version},
        )
    except _TRANSIENT_ERRORS as exc:
        if attempt < _MAX_RETRIES:
            logger.warning("planner.refine.retrying lecture=%s attempt=%d", lecture_id, attempt + 1)
            await publish_progress(
                lecture.plan_id,
                {
                    "type": "lecture.retrying",
                    "lecture_id": str(lecture.id),
                    "attempt": attempt + 1,
                    "max_attempts": _MAX_RETRIES,
                },
            )
            raise
        logger.exception("planner.refine.failed lecture=%s (retries exhausted)", lecture_id)
        await _mark_failed(lecture, exc)
    except Exception as exc:
        logger.exception("planner.refine.failed lecture=%s", lecture_id)
        await _mark_failed(lecture, exc)


@celery_app.task(bind=True, name="planner.generate_lecture", max_retries=_MAX_RETRIES)
def generate_lecture_task(self, lecture_id: str) -> None:
    try:
        run_async(generate_lecture(lecture_id, attempt=self.request.retries))
    except _TRANSIENT_ERRORS as exc:
        raise self.retry(exc=exc, countdown=min(5 * (2**self.request.retries), 60)) from exc


@celery_app.task(bind=True, name="planner.refine_lecture", max_retries=_MAX_RETRIES)
def refine_lecture_task(self, lecture_id: str, transform: str, target_language: str | None = None) -> None:
    try:
        run_async(refine_lecture(lecture_id, transform, target_language, attempt=self.request.retries))
    except _TRANSIENT_ERRORS as exc:
        raise self.retry(exc=exc, countdown=min(5 * (2**self.request.retries), 60)) from exc
