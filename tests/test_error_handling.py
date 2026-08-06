from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from ucenik.enum.user_role import UserRole


async def test_unexpected_exception_returns_clean_500(make_user):
    """A totally unhandled exception (not one of our ServiceError types) must
    never leak a stack trace or driver internals to the client - just an
    opaque 500. This is what errors/handlers.py's catch-all is for.

    Uses its own client with raise_app_exceptions=False: ASGITransport
    re-raises unhandled server exceptions into the test by default (good for
    every other test - real bugs should fail loudly), but here we're
    specifically checking what a real HTTP client would receive.
    """
    await make_user("teacher@x.com", UserRole.TEACHER, password="secret123")

    from ucenik.main import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch(
            "ucenik.models.users.User.find_one", AsyncMock(side_effect=RuntimeError("boom: unexpected db failure"))
        ):
            response = await client.post("/auth/login", json={"email": "teacher@x.com", "password": "secret123"})

    assert response.status_code == 500
    body = response.json()
    assert body == {"detail": "Internal server error"}
    assert "boom" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text
