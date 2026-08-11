"""Unit tests for services/ws_tickets.py (docs/security-hardening.md item 8)
- issue_ws_ticket/consume_ws_ticket's single-use guarantee is the whole
point of this module, so it's the one thing worth pinning down here.
"""

from ucenik.services.ws_tickets import consume_ws_ticket, issue_ws_ticket


async def test_consume_returns_the_user_id_it_was_issued_for():
    ticket = await issue_ws_ticket("user-123")

    assert await consume_ws_ticket(ticket) == "user-123"


async def test_ticket_is_single_use():
    ticket = await issue_ws_ticket("user-123")
    await consume_ws_ticket(ticket)

    assert await consume_ws_ticket(ticket) is None  # second attempt: already consumed


async def test_unknown_ticket_returns_none():
    assert await consume_ws_ticket("never-issued") is None


async def test_two_tickets_for_the_same_user_are_independent():
    first = await issue_ws_ticket("user-123")
    second = await issue_ws_ticket("user-123")

    assert await consume_ws_ticket(first) == "user-123"
    assert await consume_ws_ticket(second) == "user-123"  # not invalidated by the other's use
