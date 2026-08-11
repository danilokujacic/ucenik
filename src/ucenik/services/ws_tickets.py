"""Short-lived, single-use tickets for the Planner progress WebSocket
(`/ws/plans/{plan_id}`, api/ws.py) - see docs/security-hardening.md item 8.

The browser's native WebSocket API can't set an Authorization header, so
some form of auth has to travel in the URL (query param) or the initial
message instead. The previous approach put the real access token there
directly - a 10-minute-lived (JWT_ACCESS_TOKEN_EXPIRE_MINUTES), full-API-
privilege credential, sitting in a URL that's exactly the kind of thing
that ends up in nginx access logs, browser history, and any browser
extension or intermediary that inspects outgoing URLs. A ticket minted
here is a random opaque string, good for one connection attempt only, and
expires in seconds rather than minutes - if one leaks via any of those
paths, the blast radius is "attacker can open one WebSocket, once, briefly"
rather than "attacker can call any endpoint as this user for the next 10
minutes."

Issuing still requires a real, normal Authorization-header-authenticated
request (api/auth.py's POST /auth/ws-ticket) - this doesn't weaken auth
anywhere, it just narrows what ends up exposed in the one place a token
has to appear in a URL.
"""

import secrets

from ucenik.core.redis import get_redis

_TICKET_TTL_SECONDS = 30  # long enough for the browser to open the socket, no longer

TICKET_LENGTH_BYTES = 32  # secrets.token_urlsafe(32) - 256 bits, not brute-forceable


def _ticket_key(ticket: str) -> str:
    return f"ws_ticket:{ticket}"


async def issue_ws_ticket(user_id: str) -> str:
    """Mints a new ticket for `user_id`, valid once, within _TICKET_TTL_SECONDS."""
    ticket = secrets.token_urlsafe(TICKET_LENGTH_BYTES)
    await get_redis().set(_ticket_key(ticket), user_id, ex=_TICKET_TTL_SECONDS)
    return ticket


async def consume_ws_ticket(ticket: str) -> str | None:
    """Atomically reads and deletes the ticket (GETDEL) - a second attempt to
    use the same ticket, whether a retry or a replay, always misses. Returns
    the user id it was issued for, or None if the ticket never existed,
    already got used, or expired.
    """
    return await get_redis().getdel(_ticket_key(ticket))
