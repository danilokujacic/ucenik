from unittest.mock import AsyncMock, patch

from tests.conftest import auth_headers, fake_completion, login
from ucenik.enum.user_role import UserRole


async def test_get_nonexistent_subject_is_404(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.get("/subjects/000000000000000000000000", headers=auth_headers(tokens))

    assert response.status_code == 404


async def test_get_malformed_subject_id_is_404_not_500(client, make_user):
    """A malformed id must not crash with a raw pydantic ValidationError (500)
    - it should look exactly like "doesn't exist" to the caller.
    """
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.get("/subjects/not-a-valid-id", headers=auth_headers(tokens))

    assert response.status_code == 404


async def test_student_cannot_create_subject(client, make_user):
    await make_user("student@x.com", UserRole.STUDENT)
    tokens = await login(client, "student@x.com", "password123")

    response = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(tokens))

    assert response.status_code == 403


async def test_teacher_creates_and_owns_subject(client, make_user):
    teacher = await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.post(
        "/subjects", json={"name": "Math 101", "description": "basics"}, headers=auth_headers(tokens)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Math 101"
    assert body["teacher_id"] == str(teacher.id)


async def test_other_teacher_cannot_modify_subject(client, make_user):
    await make_user("teacher1@x.com", UserRole.TEACHER)
    await make_user("teacher2@x.com", UserRole.TEACHER)
    t1_tokens = await login(client, "teacher1@x.com", "password123")
    t2_tokens = await login(client, "teacher2@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(t1_tokens))
    subject_id = create.json()["id"]

    response = await client.patch(f"/subjects/{subject_id}", json={"name": "Hacked"}, headers=auth_headers(t2_tokens))

    assert response.status_code == 403


async def test_unenrolled_student_cannot_view_subject(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    await make_user("student@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")
    s_tokens = await login(client, "student@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(t_tokens))
    subject_id = create.json()["id"]

    response = await client.get(f"/subjects/{subject_id}", headers=auth_headers(s_tokens))

    assert response.status_code == 403


async def test_enrolled_student_can_view_subject_and_it_appears_in_their_list(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    student = await make_user("student@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")
    s_tokens = await login(client, "student@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(t_tokens))
    subject_id = create.json()["id"]

    enroll = await client.post(
        f"/subjects/{subject_id}/enrollments", json={"student_id": str(student.id)}, headers=auth_headers(t_tokens)
    )
    assert enroll.status_code == 201

    view = await client.get(f"/subjects/{subject_id}", headers=auth_headers(s_tokens))
    assert view.status_code == 200

    listing = await client.get("/subjects", headers=auth_headers(s_tokens))
    assert [s["name"] for s in listing.json()] == ["Math"]


async def test_duplicate_enrollment_rejected(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    student = await make_user("student@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(t_tokens))
    subject_id = create.json()["id"]

    first = await client.post(
        f"/subjects/{subject_id}/enrollments", json={"student_id": str(student.id)}, headers=auth_headers(t_tokens)
    )
    assert first.status_code == 201

    second = await client.post(
        f"/subjects/{subject_id}/enrollments", json={"student_id": str(student.id)}, headers=auth_headers(t_tokens)
    )
    assert second.status_code == 409


async def test_unenroll_removes_access(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    student = await make_user("student@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")
    s_tokens = await login(client, "student@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(t_tokens))
    subject_id = create.json()["id"]

    await client.post(
        f"/subjects/{subject_id}/enrollments", json={"student_id": str(student.id)}, headers=auth_headers(t_tokens)
    )
    assert (await client.get(f"/subjects/{subject_id}", headers=auth_headers(s_tokens))).status_code == 200

    unenroll = await client.delete(f"/subjects/{subject_id}/enrollments/{student.id}", headers=auth_headers(t_tokens))
    assert unenroll.status_code == 204

    assert (await client.get(f"/subjects/{subject_id}", headers=auth_headers(s_tokens))).status_code == 403


async def test_admin_bypasses_ownership_checks(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    await make_user("admin@x.com", UserRole.ADMIN)
    t_tokens = await login(client, "teacher@x.com", "password123")
    a_tokens = await login(client, "admin@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(t_tokens))
    subject_id = create.json()["id"]

    response = await client.patch(
        f"/subjects/{subject_id}", json={"name": "Renamed by admin"}, headers=auth_headers(a_tokens)
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed by admin"


async def test_delete_subject_cascades_enrollments(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    student = await make_user("student@x.com", UserRole.STUDENT)
    t_tokens = await login(client, "teacher@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Math"}, headers=auth_headers(t_tokens))
    subject_id = create.json()["id"]
    await client.post(
        f"/subjects/{subject_id}/enrollments", json={"student_id": str(student.id)}, headers=auth_headers(t_tokens)
    )

    delete = await client.delete(f"/subjects/{subject_id}", headers=auth_headers(t_tokens))
    assert delete.status_code == 204

    from ucenik.models.enrollments import Enrollment

    remaining = await Enrollment.find(Enrollment.subject_id == subject_id).to_list()
    assert remaining == []


async def test_delete_subject_cascades_documents_and_their_chunks(client, make_user):
    """Deleting a subject must not orphan its Document rows, Chroma chunks,
    or S3 object - see api/subjects.py's delete_subject.
    """
    import chromadb

    from ucenik.core.storage import file_exists
    from ucenik.models.documents import Document
    from ucenik.rag.vector_store import _get_client as get_chroma_client

    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    create = await client.post("/subjects", json={"name": "Biology"}, headers=auth_headers(tokens))
    subject_id = create.json()["id"]

    text = b"Mitosis is the process by which a single cell divides into two daughter cells."
    with patch(
        "ucenik.rag.contextualizer.complete",
        AsyncMock(return_value=fake_completion("This chunk is from a biology chapter on mitosis.")),
    ):
        upload = await client.post(
            f"/subjects/{subject_id}/documents",
            files={"file": ("mitosis.txt", text, "text/plain")},
            headers=auth_headers(tokens),
        )
        assert upload.status_code == 201
        document_id = upload.json()["id"]

        detail = await client.get(f"/subjects/{subject_id}/documents/{document_id}", headers=auth_headers(tokens))
    assert detail.json()["status"] == "ready", detail.json()

    document = await Document.get(document_id)
    file_hash = document.file_hash
    assert await file_exists(file_hash)

    delete = await client.delete(f"/subjects/{subject_id}", headers=auth_headers(tokens))
    assert delete.status_code == 204

    assert await Document.get(document_id) is None
    assert not await file_exists(file_hash)

    chroma_client = await get_chroma_client()
    try:
        await chroma_client.get_collection(name=f"subject_{subject_id}")
        collection_still_exists = True
    except chromadb.errors.NotFoundError:
        collection_still_exists = False
    assert not collection_still_exists
