from ucenik.enum.user_role import UserRole
from tests.conftest import auth_headers, login


async def test_login_success(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER, password="secret123")

    response = await client.post("/auth/login", json={"email": "teacher@x.com", "password": "secret123"})

    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] == 600  # 10 minutes, from settings
    assert "access_token" in body
    assert "refresh_token" in body


async def test_login_wrong_password(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER, password="secret123")

    response = await client.post("/auth/login", json={"email": "teacher@x.com", "password": "wrong"})

    assert response.status_code == 401


async def test_login_unknown_email(client):
    response = await client.post("/auth/login", json={"email": "nobody@x.com", "password": "whatever"})

    assert response.status_code == 401


async def test_me_requires_token(client):
    response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_returns_current_user_without_password_hash(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER, full_name="Ms. Teacher")
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.get("/auth/me", headers=auth_headers(tokens))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "teacher@x.com"
    assert body["full_name"] == "Ms. Teacher"
    assert "password_hash" not in body
    assert "hashed_password" not in body


async def test_refresh_issues_new_access_token(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    assert response.status_code == 200
    assert response.json()["expires_in"] == 600


async def test_refresh_rejects_access_token(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})

    assert response.status_code == 401


async def test_logout_revokes_refresh_token(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    logout_response = await client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert logout_response.status_code == 204

    refresh_response = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh_response.status_code == 401
