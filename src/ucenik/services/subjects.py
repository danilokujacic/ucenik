"""Subject lifecycle + enrollment management - see api/subjects.py for the
request/response shapes and permission dependencies (core/permissions.py).
"""

from beanie import PydanticObjectId
from beanie.operators import In
from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError

from ucenik.core.storage import delete_file
from ucenik.enum.user_role import UserRole
from ucenik.errors.persistence import translate_duplicate_key
from ucenik.errors.service import DuplicateResourceError, NotFoundError, parse_object_id
from ucenik.models.documents import Document
from ucenik.models.enrollments import Enrollment
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.rag.vector_store import delete_subject_collection


async def create_subject(teacher_id: str, name: str, description: str | None) -> Subject:
    subject = Subject(name=name, description=description, teacher_id=teacher_id)
    await subject.insert()
    return subject


async def list_subjects_for(user: User) -> list[Subject]:
    if user.role == UserRole.ADMIN:
        return await Subject.find_all().to_list()
    if user.role == UserRole.TEACHER:
        return await Subject.find(Subject.teacher_id == str(user.id)).to_list()

    enrollments = await Enrollment.find(Enrollment.student_id == str(user.id)).to_list()
    subject_ids = [PydanticObjectId(e.subject_id) for e in enrollments]
    return await Subject.find(In(Subject.id, subject_ids)).to_list()


async def update_subject(subject: Subject, name: str | None, description: str | None) -> Subject:
    if name is not None:
        subject.name = name
    if description is not None:
        subject.description = description
    await subject.save()
    return subject


async def delete_subject(subject: Subject) -> None:
    # Cascade documents too, not just enrollments - otherwise deleting a
    # subject leaves its Document rows and vector chunks orphaned forever
    # (the subject_id they point at no longer resolves to anything).
    documents = await Document.find(Document.subject_id == str(subject.id)).to_list()
    if documents:
        await delete_subject_collection(str(subject.id))
        file_hashes = {d.file_hash for d in documents}
        await Document.find(Document.subject_id == str(subject.id)).delete()

        # only delete each S3 object if no other Document (any subject)
        # still references that content hash - see core/storage.py
        for file_hash in file_hashes:
            remaining = await Document.find_one(Document.file_hash == file_hash)
            if remaining is None:
                await delete_file(file_hash)

    await Enrollment.find(Enrollment.subject_id == str(subject.id)).delete()
    await subject.delete()


async def enroll_student(subject: Subject, student_id: str) -> tuple[Enrollment, User]:
    student = await User.get(parse_object_id("Student", student_id))
    if student is None or student.role != UserRole.STUDENT:
        raise NotFoundError("Student", student_id)

    enrollment = Enrollment(subject_id=str(subject.id), student_id=str(student.id))
    try:
        await enrollment.insert()
    except MongoDuplicateKeyError as exc:
        raise DuplicateResourceError("Enrollment", student_id) from translate_duplicate_key("Enrollment", exc)

    return enrollment, student


async def list_enrollments_with_students(subject: Subject) -> list[tuple[Enrollment, User]]:
    enrollments = await Enrollment.find(Enrollment.subject_id == str(subject.id)).to_list()
    result = []
    for enrollment in enrollments:
        student = await User.get(enrollment.student_id)
        if student is None:
            continue
        result.append((enrollment, student))
    return result


async def unenroll_student(subject: Subject, student_id: str) -> None:
    enrollment = await Enrollment.find_one(
        Enrollment.subject_id == str(subject.id), Enrollment.student_id == student_id
    )
    if enrollment is None:
        raise NotFoundError("Enrollment", student_id)
    await enrollment.delete()
