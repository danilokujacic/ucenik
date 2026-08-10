from tests.conftest import auth_headers, login
from ucenik.enum.user_role import UserRole


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


async def test_non_admin_cannot_list_users(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.get("/admin/users", headers=auth_headers(tokens))

    assert response.status_code == 403


async def test_admin_lists_users(client, make_user):
    admin = await make_user("admin@x.com", UserRole.ADMIN)
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.get("/admin/users", headers=auth_headers(tokens))

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert emails == {"admin@x.com", "teacher@x.com"}
    assert str(admin.id) in {u["id"] for u in response.json()}


async def test_admin_updates_a_user(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    target = await make_user("teacher@x.com", UserRole.TEACHER, full_name="Old Name")
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.patch(
        f"/admin/users/{target.id}",
        json={"full_name": "New Name", "role": "admin"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "New Name"
    assert body["role"] == "admin"


async def test_admin_resets_a_users_password(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    await make_user("locked-out@x.com", UserRole.STUDENT, password="old-password")
    tokens = await login(client, "admin@x.com", "password123")

    target_login_before = await client.post(
        "/auth/login", json={"email": "locked-out@x.com", "password": "old-password"}
    )
    assert target_login_before.status_code == 200

    from ucenik.models.users import User

    target = await User.find_one(User.email == "locked-out@x.com")
    response = await client.patch(
        f"/admin/users/{target.id}", json={"password": "brand-new-password"}, headers=auth_headers(tokens)
    )
    assert response.status_code == 200

    old_password_login = await client.post(
        "/auth/login", json={"email": "locked-out@x.com", "password": "old-password"}
    )
    assert old_password_login.status_code == 401

    new_password_login = await client.post(
        "/auth/login", json={"email": "locked-out@x.com", "password": "brand-new-password"}
    )
    assert new_password_login.status_code == 200


async def test_admin_cannot_delete_own_account(client, make_user):
    admin = await make_user("admin@x.com", UserRole.ADMIN)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.delete(f"/admin/users/{admin.id}", headers=auth_headers(tokens))

    assert response.status_code == 409


async def test_admin_deletes_a_user_and_revokes_their_sessions(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    target = await make_user("teacher@x.com", UserRole.TEACHER)
    admin_tokens = await login(client, "admin@x.com", "password123")
    target_tokens = await login(client, "teacher@x.com", "password123")

    response = await client.delete(f"/admin/users/{target.id}", headers=auth_headers(admin_tokens))
    assert response.status_code == 204

    # the deleted user's refresh token must be revoked, not just orphaned
    refresh = await client.post("/auth/refresh", json={"refresh_token": target_tokens["refresh_token"]})
    assert refresh.status_code == 401

    login_after_delete = await client.post("/auth/login", json={"email": "teacher@x.com", "password": "password123"})
    assert login_after_delete.status_code == 401
