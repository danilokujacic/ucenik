"""Auth + authorization for the Planner progress WebSocket
(`/ws/plans/{plan_id}`, api/ws.py) - see that file's module docstring for
the transport-level notes (query-param auth, connect-before-publish).
"""

import jwt
from beanie import PydanticObjectId

from ucenik.core.permissions import is_subject_owner
from ucenik.core.security import TokenType, decode_token
from ucenik.models.plans import Plan
from ucenik.models.subjects import Subject
from ucenik.models.users import User


async def authenticate_ws_user(token: str) -> User | None:
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != TokenType.ACCESS.value:
        return None
    subject_claim = payload.get("sub", "")
    if not PydanticObjectId.is_valid(subject_claim):
        return None
    return await User.get(PydanticObjectId(subject_claim))


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
