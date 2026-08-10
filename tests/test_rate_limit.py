from ucenik.core.config import settings
from ucenik.core.redis import get_redis
from ucenik.enum.user_role import UserRole


async def _reset_rate_limit_keys() -> None:
    # Both tests' login requests also pass through the global middleware
    # (it runs on every request when enabled, not just the route(s) under
    # test), so the global key needs resetting even in the login-specific
    # test - otherwise residual count from one test bleeds into the next.
    redis = get_redis()
    await redis.delete("ratelimit:login:127.0.0.1")
    await redis.delete("ratelimit:global:127.0.0.1")


async def test_login_rate_limit_trips_after_configured_max(client, make_user):
    """Rate limiting is off globally in tests (see conftest.py) - re-enabled
    here specifically to verify the limiter itself works.
    """
    await make_user("teacher@x.com", UserRole.TEACHER)

    await _reset_rate_limit_keys()
    settings.rate_limit_enabled = True
    settings.rate_limit_login_requests_per_minute = 3
    try:
        # first 3 requests go through the normal login flow (whether they
        # succeed or fail on credentials doesn't matter - the rate limit
        # dependency runs regardless and just counts requests)
        for _ in range(3):
            response = await client.post("/auth/login", json={"email": "teacher@x.com", "password": "wrong-password"})
            assert response.status_code == 401

        # 4th request in the same window should be rejected before it even
        # touches credential checking
        limited = await client.post("/auth/login", json={"email": "teacher@x.com", "password": "wrong-password"})
        assert limited.status_code == 429
        retry_after = int(limited.headers["retry-after"])
        assert 0 < retry_after <= 60
    finally:
        settings.rate_limit_enabled = False
        settings.rate_limit_login_requests_per_minute = 10
        await _reset_rate_limit_keys()


async def test_global_rate_limit_trips_and_is_still_logged(client):
    await _reset_rate_limit_keys()
    settings.rate_limit_enabled = True
    settings.rate_limit_requests_per_minute = 3
    try:
        for _ in range(3):
            response = await client.get("/")
            assert response.status_code == 200

        limited = await client.get("/")
        assert limited.status_code == 429
        assert "rate limit" in limited.json()["detail"].lower()
        retry_after = int(limited.headers["retry-after"])
        assert 0 < retry_after <= 60
    finally:
        settings.rate_limit_enabled = False
        settings.rate_limit_requests_per_minute = 120
        await _reset_rate_limit_keys()
