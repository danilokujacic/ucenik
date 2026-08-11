"""Auth + authorization for the Planner progress WebSocket
(`/ws/plans/{plan_id}`, api/ws.py) - see that file's module docstring for
the transport-level notes (ticket-based auth, connect-before-publish), and
services/ws_tickets.py for why this is a ticket exchange rather than the
raw access token going straight into the URL.
"""

from beanie import PydanticObjectId

from ucenik.core.permissions import is_subject_owner
from ucenik.models.plans import Plan
from ucenik.models.subjects import Subject
from ucenik.models.users import User
from ucenik.services.ws_tickets import consume_ws_ticket


async def authenticate_ws_user(ticket: str) -> User | None:
    """Consumes `ticket` (single use - a second call with the same value
    always returns None, see consume_ws_ticket) and resolves it to the user
    it was issued for.
    """
    user_id = await consume_ws_ticket(ticket)
    if user_id is None or not PydanticObjectId.is_valid(user_id):
        return None
    return await User.get(PydanticObjectId(user_id))


async def get_plan_or_none(plan_id: str) -> Plan | None:
    if not PydanticObjectId.is_valid(plan_id):
        return None
    return await Plan.get(PydanticObjectId(plan_id))


async def is_authorized_for_plan(plan: Plan, user: User) -> bool:
    """Planner is teacher/admin-only end to end (see api/plans.py) - reusing
    is_subject_owner's plain predicate since this WebSocket route has no
    Depends() injection context for the HTTP-only require_subject_owner.
    """
    subject = (
        await Subject.get(PydanticObjectId(plan.subject_id)) if PydanticObjectId.is_valid(plan.subject_id) else None
    )
    return subject is not None and is_subject_owner(subject, user)
