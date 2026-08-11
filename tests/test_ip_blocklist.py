"""Unit + integration tests for services/ip_blocklist.py and its wiring
into core/rate_limit.py's middleware and api/admin_ip_blocklist.py's admin
endpoints (docs/security-hardening.md item 8).
"""

from tests.conftest import auth_headers, login
from ucenik.enum.user_role import UserRole
from ucenik.services.ip_blocklist import block_ip, is_ip_blocked, list_blocked_ips, unblock_ip


async def test_unblocked_ip_is_not_blocked():
    assert await is_ip_blocked("203.0.113.5") is False


async def test_block_then_check():
    await block_ip("203.0.113.5", "test block")
    try:
        assert await is_ip_blocked("203.0.113.5") is True
    finally:
        await unblock_ip("203.0.113.5")


async def test_unblock_removes_it():
    await block_ip("203.0.113.5", "test block")
    await unblock_ip("203.0.113.5")

    assert await is_ip_blocked("203.0.113.5") is False


async def test_ttl_expressed_block_is_listed_with_remaining_seconds():
    await block_ip("203.0.113.6", "temporary", ttl_seconds=120)
    try:
        entries = await list_blocked_ips()
        entry = next(e for e in entries if e.ip == "203.0.113.6")
        assert entry.reason == "temporary"
        assert entry.ttl_seconds is not None
        assert 0 < entry.ttl_seconds <= 120
    finally:
        await unblock_ip("203.0.113.6")


async def test_permanent_block_is_listed_with_no_ttl():
    await block_ip("203.0.113.7", "permanent")
    try:
        entries = await list_blocked_ips()
        entry = next(e for e in entries if e.ip == "203.0.113.7")
        assert entry.ttl_seconds is None
    finally:
        await unblock_ip("203.0.113.7")


async def test_blocked_client_ip_gets_403_before_reaching_the_route(client):
    """core/rate_limit.py's middleware check - unconditional, not gated by
    settings.rate_limit_enabled (see that module's docstring). /subjects
    would otherwise 401 (no auth header) - getting 403 instead confirms the
    block happens before routing/auth ever run, not just before a 200."""
    await block_ip("127.0.0.1", "integration test")
    try:
        response = await client.get("/subjects")
        assert response.status_code == 403
    finally:
        await unblock_ip("127.0.0.1")


async def test_non_admin_cannot_manage_blocklist(client, make_user):
    await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "teacher@x.com", "password123")

    response = await client.post(
        "/admin/ip-blocklist",
        json={"ip": "203.0.113.8", "reason": "abuse"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 403


async def test_admin_blocks_lists_and_unblocks_an_ip(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    tokens = await login(client, "admin@x.com", "password123")
    headers = auth_headers(tokens)

    created = await client.post(
        "/admin/ip-blocklist",
        json={"ip": "203.0.113.9", "reason": "abuse", "ttl_seconds": 300},
        headers=headers,
    )
    assert created.status_code == 204

    listed = await client.get("/admin/ip-blocklist", headers=headers)
    assert listed.status_code == 200
    assert any(e["ip"] == "203.0.113.9" for e in listed.json())

    deleted = await client.delete("/admin/ip-blocklist/203.0.113.9", headers=headers)
    assert deleted.status_code == 204

    listed_again = await client.get("/admin/ip-blocklist", headers=headers)
    assert not any(e["ip"] == "203.0.113.9" for e in listed_again.json())


async def test_invalid_ip_rejected_with_422(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.post(
        "/admin/ip-blocklist",
        json={"ip": "not-an-ip", "reason": "abuse"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 422
