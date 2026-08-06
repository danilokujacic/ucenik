from typing import Annotated

from fastapi import Depends

from ucenik.core.security import get_current_user
from ucenik.enum.user_role import UserRole
from ucenik.errors.service import NotFoundError, PermissionDeniedError, parse_object_id
from ucenik.models.documents import Document
from ucenik.models.enrollments import Enrollment
from ucenik.models.subjects import Subject
from ucenik.models.users import User


def require_role(*roles: UserRole):
    """FastAPI dependency factory: only lets requests through whose current
    user has one of `roles`.
    """

    async def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise PermissionDeniedError("insufficient permissions")
        return user

    return dependency


async def get_subject(subject_id: str) -> Subject:
    subject = await Subject.get(parse_object_id("Subject", subject_id))
    if subject is None:
        raise NotFoundError("Subject", subject_id)
    return subject


async def require_subject_owner(
    subject: Annotated[Subject, Depends(get_subject)],
    user: Annotated[User, Depends(get_current_user)],
) -> Subject:
    """Only the teacher who owns this subject, or an admin, may pass."""
    if user.role != UserRole.ADMIN and subject.teacher_id != str(user.id):
        raise PermissionDeniedError("only the owning teacher or an admin can do this")
    return subject


async def require_subject_access(
    subject: Annotated[Subject, Depends(get_subject)],
    user: Annotated[User, Depends(get_current_user)],
) -> Subject:
    """Owning teacher, admin, or a student enrolled in this subject."""
    if user.role == UserRole.ADMIN or subject.teacher_id == str(user.id):
        return subject

    if user.role == UserRole.STUDENT:
        enrolled = await Enrollment.find_one(
            Enrollment.subject_id == str(subject.id),
            Enrollment.student_id == str(user.id),
        )
        if enrolled is not None:
            return subject

    raise PermissionDeniedError("not enrolled in this subject")


async def get_document(subject_id: str, document_id: str) -> Document:
    """Fetches a document and verifies it actually belongs to `subject_id` -
    without this check, a valid document id under the wrong subject path
    would still resolve, letting a caller probe/access documents cross-subject.
    """
    document = await Document.get(parse_object_id("Document", document_id))
    if document is None or document.subject_id != subject_id:
        raise NotFoundError("Document", document_id)
    return document
