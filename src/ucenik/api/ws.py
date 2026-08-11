"""WebSocket progress feed for Planner generate/refine jobs (§Phase 6/7) -
`/ws/plans/{plan_id}`. Forwards whatever's published to core/pubsub.py's
`planner:{plan_id}` Redis channel straight through to the browser, so a
lecture-generation job running in a Celery worker can report progress
without the browser polling. See services/planner_ws.py for the auth/
authorization checks below.

Auth note: the browser's native WebSocket API can't set custom headers (no
Authorization header), so *something* has to go as a query parameter
instead - the one endpoint in this API where that's the case; every other
endpoint uses the Authorization header like normal. That something is a
short-lived, single-use ticket (`?ticket=...`), not the real access token -
see services/ws_tickets.py's module docstring for why (a raw access token
sitting in a URL - server/proxy logs, browser history - was a real
exposure risk the ticket exchange (api/auth.py's POST /auth/ws-ticket)
closes off; see docs/security-hardening.md item 8).

Connect-before-publish note: Redis pub/sub has no replay - a message
published before this endpoint's subscribe() call runs is gone forever for
this connection. The frontend needs to open this WebSocket and wait for it
to be accepted *before* triggering the generate/refine request that would
publish to it - see docs/frontend-spec.md's Planner section.
"""

from fastapi import APIRouter, WebSocket
from starlette import status
from starlette.websockets import WebSocketDisconnect

from ucenik.core.pubsub import subscribe
from ucenik.services.planner_ws import authenticate_ws_user, get_plan_or_none, is_authorized_for_plan

router = APIRouter(tags=["planner-ws"])


@router.websocket("/ws/plans/{plan_id}")
async def plan_progress(websocket: WebSocket, plan_id: str, ticket: str) -> None:
    # Rejecting the handshake (close() before accept()) rather than
    # accepting then immediately closing - a valid ASGI WebSocket response
    # to the connect event, same as FastAPI's own documented WS-auth pattern.
    user = await authenticate_ws_user(ticket)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid, expired, or already-used ticket")
        return

    plan = await get_plan_or_none(plan_id)
    if plan is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="plan not found")
        return

    if not await is_authorized_for_plan(plan, user):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="not permitted")
        return

    await websocket.accept()
    try:
        async for event in subscribe(plan_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass  # client went away - subscribe()'s own `finally` unsubscribes
