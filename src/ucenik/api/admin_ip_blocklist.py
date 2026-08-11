"""Admin-only CRUD over the IP blocklist (docs/security-hardening.md item
8) - see services/ip_blocklist.py for the actual Redis-backed logic and
core/rate_limit.py for where a blocked IP actually gets denied.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, IPvAnyAddress

from ucenik.core.permissions import require_role
from ucenik.enum.user_role import UserRole
from ucenik.models.users import User
from ucenik.services import ip_blocklist as ip_blocklist_service

router = APIRouter(prefix="/admin/ip-blocklist", tags=["admin"])


class BlockIpRequest(BaseModel):
    ip: IPvAnyAddress  # rejects anything that isn't a real IPv4/IPv6 address with a normal 422
    reason: str
    ttl_seconds: int | None = None  # omitted/None = permanent, until explicitly unblocked


@router.get("", response_model=list[ip_blocklist_service.BlockedIp])
async def list_blocked_ips(
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> list[ip_blocklist_service.BlockedIp]:
    return await ip_blocklist_service.list_blocked_ips()


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def block_ip(
    payload: BlockIpRequest,
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> None:
    await ip_blocklist_service.block_ip(str(payload.ip), payload.reason, payload.ttl_seconds)


@router.delete("/{ip}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_ip(ip: str, _admin: Annotated[User, Depends(require_role(UserRole.ADMIN))]) -> None:
    await ip_blocklist_service.unblock_ip(ip)
