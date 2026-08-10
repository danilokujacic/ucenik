"""Planner: Lectures + version history routes - see services/lectures.py for
the actual logic and workers/planner_tasks.py for the Celery jobs it
dispatches.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator

from ucenik.core.permissions import require_subject_owner
from ucenik.core.security import get_current_user
from ucenik.models.lecture_versions import VersionSource
from ucenik.models.lectures import Lecture, LectureStatus
from ucenik.models.plans import Plan
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.rag.refiner import RefineTransform
from ucenik.services import lectures as lectures_service
from ucenik.services.lectures import get_lecture_or_404 as get_lecture
from ucenik.services.plans import get_plan_or_404 as get_plan

router = APIRouter(prefix="/subjects/{subject_id}/plans/{plan_id}/lectures", tags=["planner"])


class CreateLectureRequest(BaseModel):
    title: str
    topic: str = Field(min_length=1, max_length=2000)
    order: int = 0


class ManualEditRequest(BaseModel):
    content: str = Field(min_length=1)


class RefineRequest(BaseModel):
    transform: RefineTransform
    target_language: str | None = None

    @model_validator(mode="after")
    def _require_target_language_for_translate(self) -> RefineRequest:
        if self.transform == RefineTransform.TRANSLATE and not self.target_language:
            raise ValueError("target_language is required when transform is 'translate'")
        return self


class LecturePublic(BaseModel):
    id: str
    plan_id: str
    order: int
    title: str
    topic: str
    status: LectureStatus
    error: str | None
    current_version: int
    content: str | None  # denormalized from the current LectureVersion, for convenience


class LectureVersionPublic(BaseModel):
    version: int
    content: str
    source: VersionSource
    change_summary: str | None
    created_at: datetime


async def _to_public(lecture: Lecture) -> LecturePublic:
    return LecturePublic(
        id=str(lecture.id),
        plan_id=lecture.plan_id,
        order=lecture.order,
        title=lecture.title,
        topic=lecture.topic,
        status=lecture.status,
        error=lecture.error,
        current_version=lecture.current_version,
        content=await lectures_service.get_current_content(lecture),
    )


@router.post("", response_model=LecturePublic, status_code=status.HTTP_202_ACCEPTED)
async def create_lecture(
    payload: CreateLectureRequest,
    plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
    user: Annotated[User, Depends(get_current_user)],
) -> LecturePublic:
    lecture = await lectures_service.create_lecture(plan, user, payload.title, payload.topic, payload.order)
    return await _to_public(lecture)


@router.get("", response_model=list[LecturePublic])
async def list_lectures(
    plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> list[LecturePublic]:
    lectures = await lectures_service.list_lectures(plan)
    return [await _to_public(lecture) for lecture in lectures]


@router.get("/{lecture_id}", response_model=LecturePublic)
async def get_lecture_details(
    lecture: Annotated[Lecture, Depends(get_lecture)],
    _plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> LecturePublic:
    return await _to_public(lecture)


@router.patch("/{lecture_id}", response_model=LecturePublic)
async def manual_edit_lecture(
    payload: ManualEditRequest,
    lecture: Annotated[Lecture, Depends(get_lecture)],
    _plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> LecturePublic:
    lecture = await lectures_service.manual_edit_lecture(lecture, payload.content)
    return await _to_public(lecture)


@router.post("/{lecture_id}/refine", response_model=LecturePublic, status_code=status.HTTP_202_ACCEPTED)
async def refine_lecture_endpoint(
    payload: RefineRequest,
    lecture: Annotated[Lecture, Depends(get_lecture)],
    _plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> LecturePublic:
    lecture = await lectures_service.refine_lecture(lecture, payload.transform, payload.target_language)
    return await _to_public(lecture)


@router.post("/{lecture_id}/retry", response_model=LecturePublic, status_code=status.HTTP_202_ACCEPTED)
async def retry_lecture(
    lecture: Annotated[Lecture, Depends(get_lecture)],
    _plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> LecturePublic:
    lecture = await lectures_service.retry_lecture(lecture)
    return await _to_public(lecture)


@router.get("/{lecture_id}/versions", response_model=list[LectureVersionPublic])
async def list_lecture_versions(
    lecture: Annotated[Lecture, Depends(get_lecture)],
    _plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> list[LectureVersionPublic]:
    versions = await lectures_service.list_lecture_versions(lecture)
    return [
        LectureVersionPublic(
            version=v.version,
            content=v.content,
            source=v.source,
            change_summary=v.change_summary,
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.post("/{lecture_id}/versions/{version}/rollback", response_model=LecturePublic)
async def rollback_lecture_version(
    version: int,
    lecture: Annotated[Lecture, Depends(get_lecture)],
    _plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> LecturePublic:
    lecture = await lectures_service.rollback_lecture_version(lecture, version)
    return await _to_public(lecture)


@router.delete("/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lecture(
    lecture: Annotated[Lecture, Depends(get_lecture)],
    _plan: Annotated[Plan, Depends(get_plan)],
    _subject: Annotated[Subject, Depends(require_subject_owner)],
) -> None:
    await lectures_service.delete_lecture(lecture)
