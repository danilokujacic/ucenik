"""Planner: Lectures + version history (§Phase 7). Teacher/admin only end to
end, same rule as services/plans.py.

Generate and refine are async - both return 202 with the Lecture in a
non-terminal status, then dispatch a Celery task (workers/planner_tasks.py)
that reports progress over `/ws/plans/{plan_id}` (api/ws.py) and eventually
lands the lecture back in `ready` or `failed`. Manual edit and rollback are
synchronous (no LLM call - just a database write, no reason to make the
caller wait on a background job round-trip for that).
"""

from datetime import UTC, datetime

from ucenik.errors.service import InvalidStateError, NotFoundError, parse_object_id
from ucenik.models.lecture_versions import LectureVersion, VersionSource
from ucenik.models.lectures import Lecture, LectureStatus
from ucenik.models.plans import Plan
from ucenik.models.users import User
from ucenik.rag.refiner import RefineTransform
from ucenik.workers.planner_tasks import generate_lecture_task, refine_lecture_task


async def get_lecture_or_404(plan_id: str, lecture_id: str) -> Lecture:
    lecture = await Lecture.get(parse_object_id("Lecture", lecture_id))
    if lecture is None or lecture.plan_id != plan_id:
        raise NotFoundError("Lecture", lecture_id)
    return lecture


async def get_current_content(lecture: Lecture) -> str | None:
    """The current version's content, denormalized onto LecturePublic for
    convenience - `None` until `current_version > 0`.
    """
    if not lecture.current_version:
        return None
    version = await LectureVersion.find_one(
        LectureVersion.lecture_id == str(lecture.id), LectureVersion.version == lecture.current_version
    )
    return version.content if version else None


async def create_lecture(plan: Plan, user: User, title: str, topic: str, order: int) -> Lecture:
    lecture = Lecture(
        plan_id=str(plan.id),
        subject_id=plan.subject_id,
        order=order,
        title=title,
        topic=topic,
        created_by=str(user.id),
    )
    await lecture.insert()
    generate_lecture_task.delay(str(lecture.id))
    return lecture


async def list_lectures(plan: Plan) -> list[Lecture]:
    return await Lecture.find(Lecture.plan_id == str(plan.id)).sort(+Lecture.order).to_list()


async def manual_edit_lecture(lecture: Lecture, content: str) -> Lecture:
    next_version = (lecture.current_version or 0) + 1
    await LectureVersion(
        lecture_id=str(lecture.id), version=next_version, content=content, source=VersionSource.MANUAL_EDIT
    ).insert()
    lecture.current_version = next_version
    lecture.status = LectureStatus.READY
    lecture.error = None
    lecture.updated_at = datetime.now(UTC)
    await lecture.save()
    return lecture


async def refine_lecture(lecture: Lecture, transform: RefineTransform, target_language: str | None) -> Lecture:
    if lecture.current_version == 0:
        raise InvalidStateError("cannot refine a lecture with no generated version yet")
    if lecture.status == LectureStatus.GENERATING:
        raise InvalidStateError("a generation/refine job is already in progress for this lecture")

    refine_lecture_task.delay(str(lecture.id), transform.value, target_language)
    return lecture


async def retry_lecture(lecture: Lecture) -> Lecture:
    """The retry path a failed-with-no-version-at-all lecture otherwise has
    none of: `refine_lecture` requires `current_version > 0`, so a lecture
    that failed its very first generation used to be stuck at
    delete-and-recreate (docs/backlog.md item 7). Also covers a failed
    refine, replaying its last transform (workers/planner_tasks.py sets
    `last_refine_transform`/`last_refine_target_language` before every
    refine attempt, success or failure, specifically so this has something
    to replay).
    """
    if lecture.status != LectureStatus.FAILED:
        raise InvalidStateError("can only retry a lecture that's currently failed")

    if lecture.current_version == 0:
        generate_lecture_task.delay(str(lecture.id))
    elif lecture.last_refine_transform is not None:
        refine_lecture_task.delay(str(lecture.id), lecture.last_refine_transform, lecture.last_refine_target_language)
    else:
        # Not reachable through this codebase's own code paths today (a
        # failure with current_version > 0 only ever comes from a refine
        # attempt, which always sets last_refine_transform first) - kept
        # as a real error rather than a silent no-op in case that
        # invariant ever stops holding.
        raise InvalidStateError("no prior generation or refine attempt to retry")

    return lecture


async def list_lecture_versions(lecture: Lecture) -> list[LectureVersion]:
    return (
        await LectureVersion.find(LectureVersion.lecture_id == str(lecture.id)).sort(+LectureVersion.version).to_list()
    )


async def rollback_lecture_version(lecture: Lecture, version: int) -> Lecture:
    target = await LectureVersion.find_one(
        LectureVersion.lecture_id == str(lecture.id), LectureVersion.version == version
    )
    if target is None:
        raise NotFoundError("LectureVersion", str(version))

    next_version = lecture.current_version + 1
    await LectureVersion(
        lecture_id=str(lecture.id),
        version=next_version,
        content=target.content,
        source=VersionSource.ROLLBACK,
        change_summary=f"rolled back to v{version}",
    ).insert()
    lecture.current_version = next_version
    lecture.status = LectureStatus.READY
    lecture.error = None
    lecture.updated_at = datetime.now(UTC)
    await lecture.save()
    return lecture


async def delete_lecture(lecture: Lecture) -> None:
    await LectureVersion.find(LectureVersion.lecture_id == str(lecture.id)).delete()
    await lecture.delete()
