from datetime import datetime
from typing import Annotated

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError

from ucenik.core.permissions import require_role, require_subject_access, require_subject_owner
from ucenik.core.security import get_current_user
from ucenik.enum.user_role import UserRole
from ucenik.errors.persistence import translate_duplicate_key
from ucenik.errors.service import DuplicateResourceError, NotFoundError, parse_object_id
from ucenik.models.enrollments import Enrollment
from ucenik.models.subjects import Subject
from ucenik.models.users import User

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
    return SubjectPublic(id=str(subject.id), name=subject.name, description=subject.description, teacher_id=subject.teacher_id)


@router.post("", response_model=SubjectPublic, status_code=status.HTTP_201_CREATED)
async def create_subject(
    payload: CreateSubjectRequest,
    teacher: Annotated[User, Depends(require_role(UserRole.TEACHER))],
) -> SubjectPublic:
    subject = Subject(name=payload.name, description=payload.description, teacher_id=str(teacher.id))
    await subject.insert()
    return _to_public(subject)


@router.get("", response_model=list[SubjectPublic])
async def list_subjects(user: Annotated[User, Depends(get_current_user)]) -> list[SubjectPublic]:
    if user.role == UserRole.ADMIN:
        subjects = await Subject.find_all().to_list()
    elif user.role == UserRole.TEACHER:
        subjects = await Subject.find(Subject.teacher_id == str(user.id)).to_list()
    else:
        enrollments = await Enrollment.find(Enrollment.student_id == str(user.id)).to_list()
        subject_ids = [PydanticObjectId(e.subject_id) for e in enrollments]
        subjects = await Subject.find(In(Subject.id, subject_ids)).to_list()
    return [_to_public(s) for s in subjects]


@router.get("/{subject_id}", response_model=SubjectPublic)
async def get_subject_details(subject: Annotated[Subject, Depends(require_subject_access)]) -> SubjectPublic:
    return _to_public(subject)


@router.patch("/{subject_id}", response_model=SubjectPublic)
async def update_subject(
    payload: UpdateSubjectRequest,
    subject: Annotated[Subject, Depends(require_subject_owner)],
) -> SubjectPublic:
    if payload.name is not None:
        subject.name = payload.name
    if payload.description is not None:
        subject.description = payload.description
    await subject.save()
    return _to_public(subject)


@router.delete("/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(subject: Annotated[Subject, Depends(require_subject_owner)]) -> None:
    await Enrollment.find(Enrollment.subject_id == str(subject.id)).delete()
    await subject.delete()


@router.post("/{subject_id}/enrollments", response_model=EnrollmentPublic, status_code=status.HTTP_201_CREATED)
async def enroll_student(
    payload: EnrollRequest,
    subject: Annotated[Subject, Depends(require_subject_owner)],
) -> EnrollmentPublic:
    student = await User.get(parse_object_id("Student", payload.student_id))
    if student is None or student.role != UserRole.STUDENT:
        raise NotFoundError("Student", payload.student_id)

    enrollment = Enrollment(subject_id=str(subject.id), student_id=str(student.id))
    try:
        await enrollment.insert()
    except MongoDuplicateKeyError as exc:
        raise DuplicateResourceError("Enrollment", payload.student_id) from translate_duplicate_key("Enrollment", exc)

    return EnrollmentPublic(
        student_id=str(student.id),
        email=student.email,
        full_name=student.full_name,
        enrolled_at=enrollment.enrolled_at,
    )


@router.get("/{subject_id}/enrollments", response_model=list[EnrollmentPublic])
async def list_enrollments(subject: Annotated[Subject, Depends(require_subject_owner)]) -> list[EnrollmentPublic]:
    enrollments = await Enrollment.find(Enrollment.subject_id == str(subject.id)).to_list()
    result = []
    for enrollment in enrollments:
        student = await User.get(enrollment.student_id)
        if student is None:
            continue
        result.append(
            EnrollmentPublic(
                student_id=enrollment.student_id,
                email=student.email,
                full_name=student.full_name,
                enrolled_at=enrollment.enrolled_at,
            )
        )
    return result


@router.delete("/{subject_id}/enrollments/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_student(
    student_id: str,
    subject: Annotated[Subject, Depends(require_subject_owner)],
) -> None:
    enrollment = await Enrollment.find_one(Enrollment.subject_id == str(subject.id), Enrollment.student_id == student_id)
    if enrollment is None:
        raise NotFoundError("Enrollment", student_id)
    await enrollment.delete()
