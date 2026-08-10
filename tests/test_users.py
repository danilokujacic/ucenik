from tests.conftest import auth_headers, login
from ucenik.enum.user_role import UserRole


async def test_lookup_requires_authentication(client):
    response = await client.get("/users/students/lookup", params={"email": "student@x.com"})

    assert response.status_code == 401


async def test_student_cannot_use_lookup(client, make_user):
    await make_user("student@x.com", UserRole.STUDENT)
    tokens = await login(client, "student@x.com", "password123")

    response = await client.get(
        "/users/students/lookup", params={"email": "student@x.com"}, headers=auth_headers(tokens)
    )

    assert response.status_code == 403


async def test_teacher_looks_up_student_by_email(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    student = await make_user("student@x.com", UserRole.STUDENT, full_name="Alex Student")
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.get(
        "/users/students/lookup", params={"email": "student@x.com"}, headers=auth_headers(tokens)
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"id": str(student.id), "email": "student@x.com", "full_name": "Alex Student"}


async def test_admin_can_also_use_lookup(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    await make_user("student@x.com", UserRole.STUDENT)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.get(
        "/users/students/lookup", params={"email": "student@x.com"}, headers=auth_headers(tokens)
    )

    assert response.status_code == 200


async def test_lookup_unknown_email_is_404(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.get(
        "/users/students/lookup", params={"email": "nobody@x.com"}, headers=auth_headers(tokens)
    )

    assert response.status_code == 404


async def test_lookup_does_not_leak_non_student_accounts(client, make_user):
    """A teacher/admin email must 404 exactly like a nonexistent one - this
    endpoint shouldn't let a teacher probe whether an email belongs to
    another teacher or admin account.
    """
    await make_user("teacher@x.com", UserRole.TEACHER)
    await make_user("other-teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.get(
        "/users/students/lookup", params={"email": "other-teacher@x.com"}, headers=auth_headers(tokens)
    )

    assert response.status_code == 404


async def test_quota_requires_authentication(client):
    response = await client.get("/users/me/quota")

    assert response.status_code == 401


async def test_quota_starts_at_zero_and_reports_the_configured_limit(client, make_user):
    from ucenik.core.config import settings

    await make_user("student@x.com", UserRole.STUDENT)
    tokens = await login(client, "student@x.com", "password123")

    response = await client.get("/users/me/quota", headers=auth_headers(tokens))

    assert response.status_code == 200
    body = response.json()
    assert body["used_tokens"] == 0
    assert body["limit"] == settings.max_quota
    assert "resets_at" in body


async def test_quota_reflects_real_usage_and_is_per_user(client, make_user):
    from ucenik.core.quota import record_usage

    student = await make_user("student@x.com", UserRole.STUDENT)
    other = await make_user("other@x.com", UserRole.STUDENT)
    tokens = await login(client, "student@x.com", "password123")

    await record_usage(str(student.id), 500)
    await record_usage(str(other.id), 999)  # a different user's usage must not bleed in

    response = await client.get("/users/me/quota", headers=auth_headers(tokens))

    assert response.status_code == 200
    assert response.json()["used_tokens"] == 500
