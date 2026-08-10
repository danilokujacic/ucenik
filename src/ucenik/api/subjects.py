from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from ucenik.core.permissions import require_role, require_subject_access, require_subject_owner
from ucenik.core.security import get_current_user
from ucenik.enum.user_role import UserRole
from ucenik.models.enrollments import Enrollment
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.services import subjects as subjects_service

router = APIRouter(prefix="/subjects", tags=["subjects"])


class CreateSubjectRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateSubjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class SubjectPublic(BaseModel):
    id: str
    name: str
    description: str | None
    teacher_id: str


class EnrollRequest(BaseModel):
    student_id: str


class EnrollmentPublic(BaseModel):
    student_id: str
    email: str
    full_name: str
    enrolled_at: datetime


def _to_public(subject: Subject) -> SubjectPublic:
    return SubjectPublic(
        id=str(subject.id), name=subject.name, description=subject.description, teacher_id=subject.teacher_id
    )


def _enrollment_to_public(enrollment: Enrollment, student: User) -> EnrollmentPublic:
    return EnrollmentPublic(
        student_id=enrollment.student_id,
        email=student.email,
        full_name=student.full_name,
        enrolled_at=enrollment.enrolled_at,
    )


@router.post("", response_model=SubjectPublic, status_code=status.HTTP_201_CREATED)
async def create_subject(
    payload: CreateSubjectRequest,
    teacher: Annotated[User, Depends(require_role(UserRole.TEACHER))],
) -> SubjectPublic:
    subject = await subjects_service.create_subject(str(teacher.id), payload.name, payload.description)
    return _to_public(subject)


@router.get("", response_model=list[SubjectPublic])
async def list_subjects(user: Annotated[User, Depends(get_current_user)]) -> list[SubjectPublic]:
    subjects = await subjects_service.list_subjects_for(user)
    return [_to_public(s) for s in subjects]


@router.get("/{subject_id}", response_model=SubjectPublic)
async def get_subject_details(subject: Annotated[Subject, Depends(require_subject_access)]) -> SubjectPublic:
    return _to_public(subject)


@router.patch("/{subject_id}", response_model=SubjectPublic)
async def update_subject(
    payload: UpdateSubjectRequest,
    subject: Annotated[Subject, Depends(require_subject_owner)],
) -> SubjectPublic:
    subject = await subjects_service.update_subject(subject, payload.name, payload.description)
    return _to_public(subject)


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(subject: Annotated[Subject, Depends(require_subject_owner)]) -> None:
    await subjects_service.delete_subject(subject)


@router.post("/{subject_id}/enrollments", response_model=EnrollmentPublic, status_code=status.HTTP_201_CREATED)
async def enroll_student(
    payload: EnrollRequest,
    subject: Annotated[Subject, Depends(require_subject_owner)],
) -> EnrollmentPublic:
    enrollment, student = await subjects_service.enroll_student(subject, payload.student_id)
    return _enrollment_to_public(enrollment, student)


@router.get("/{subject_id}/enrollments", response_model=list[EnrollmentPublic])
async def list_enrollments(subject: Annotated[Subject, Depends(require_subject_owner)]) -> list[EnrollmentPublic]:
    pairs = await subjects_service.list_enrollments_with_students(subject)
    return [_enrollment_to_public(e, s) for e, s in pairs]


@router.delete("/{subject_id}/enrollments/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_student(
    student_id: str,
    subject: Annotated[Subject, Depends(require_subject_owner)],
) -> None:
    await subjects_service.unenroll_student(subject, student_id)
