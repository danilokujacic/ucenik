import uuid
from unittest.mock import AsyncMock, patch

from tests.conftest import auth_headers, fake_completion, login
from ucenik.core.config import settings
from ucenik.core.quota import _quota_key, check_quota, record_usage
from ucenik.core.redis import get_redis
from ucenik.enum.user_role import UserRole
from ucenik.errors.service import QuotaExceededError


def _unique_user_id() -> str:
    # each test gets its own key - the quota window is per-UTC-day and
    # Redis isn't reset between test runs the way Mongo is (see
    # tests/conftest.py's _clean_collections), so a fixed id would
    # accumulate across repeated runs on the same day.
    return f"quota-test-{uuid.uuid4()}"


async def test_check_quota_passes_when_under_limit():
    await check_quota(_unique_user_id())  # should not raise


async def test_record_usage_accumulates_and_check_quota_trips_over_limit():
    user_id = _unique_user_id()
    original_limit = settings.max_quota
    settings.max_quota = 100
    try:
        await record_usage(user_id, 60)
        await check_quota(user_id)  # 60 < 100, still fine

        await record_usage(user_id, 50)  # now 110 >= 100
        try:
            await check_quota(user_id)
            raise AssertionError("expected QuotaExceededError")
        except QuotaExceededError as exc:
            assert exc.used == 110
            assert exc.limit == 100
            # resets at UTC midnight, so "now" is always well under 24h away
            assert 0 < exc.retry_after_seconds <= 86400
    finally:
        settings.max_quota = original_limit
        await get_redis().delete(_quota_key(user_id))


async def test_ingest_fails_cleanly_when_quota_already_exceeded(client, make_user):
    """A user who already blew through quota gets a clean failed Document,
    not a crash - quota errors flow through the same try/except as any
    other ingest failure (rag/ingest.py).
    """
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    original_limit = settings.max_quota
    settings.max_quota = 0  # already exhausted
    try:
        subject = await client.post("/subjects", json={"name": "Quota Test"}, headers=auth_headers(tokens))
        subject_id = subject.json()["id"]

        with patch(
            "ucenik.rag.contextualizer.complete",
            AsyncMock(return_value=fake_completion("unused - should never be called")),
        ) as mock_complete:
            upload = await client.post(
                f"/subjects/{subject_id}/documents",
                files={"file": ("quota.txt", b"some content that needs a chunk", "text/plain")},
                headers=auth_headers(tokens),
            )
            document_id = upload.json()["id"]

            detail = await client.get(f"/subjects/{subject_id}/documents/{document_id}", headers=auth_headers(tokens))

        assert detail.json()["status"] == "failed"
        assert "quota" in detail.json()["error"].lower()
        mock_complete.assert_not_called()  # check_quota runs before the LLM call, not after
    finally:
        settings.max_quota = original_limit
