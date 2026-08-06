from ucenik.enum.user_role import UserRole
from tests.conftest import auth_headers, login


async def test_create_user_requires_authentication(client):
    response = await client.post(
        "/admin/users",
        json={"email": "new@x.com", "password": "pw", "full_name": "New", "role": "student"},
    )

    assert response.status_code == 401


async def test_non_admin_cannot_create_user(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.post(
        "/admin/users",
        json={"email": "new@x.com", "password": "pw", "full_name": "New", "role": "student"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 403


async def test_admin_creates_user(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.post(
        "/admin/users",
        json={"email": "new-teacher@x.com", "password": "pw123456", "full_name": "New Teacher", "role": "teacher"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new-teacher@x.com"
    assert body["role"] == "teacher"
    assert "password_hash" not in body

    # and the created user can actually log in
    login_response = await client.post("/auth/login", json={"email": "new-teacher@x.com", "password": "pw123456"})
    assert login_response.status_code == 200


async def test_duplicate_email_is_rejected_without_leaking_driver_details(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    await make_user("taken@x.com", UserRole.STUDENT)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.post(
        "/admin/users",
        json={"email": "taken@x.com", "password": "pw", "full_name": "Dup", "role": "student"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    # message should be ours, not a raw pymongo/driver error leaking internals
    assert "taken@x.com" in detail
    assert "E11000" not in detail
    assert "pymongo" not in detail.lower()
