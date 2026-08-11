from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from ucenik.api.users import UserPublic
from ucenik.core.rate_limit import check_login_rate_limit
from ucenik.core.security import get_current_user
from ucenik.models.users import User
from ucenik.services import auth as auth_service
from ucenik.services.ws_tickets import issue_ws_ticket

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class WsTicketResponse(BaseModel):
    ticket: str


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, _rl: Annotated[None, Depends(check_login_rate_limit)]) -> TokenResponse:
    user = await auth_service.authenticate(payload.email, payload.password)
    access_token, refresh_token, expires_in = await auth_service.issue_tokens(user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest) -> AccessTokenResponse:
    access_token, expires_in = await auth_service.refresh_access_token(payload.refresh_token)
    return AccessTokenResponse(access_token=access_token, expires_in=expires_in)


@router.post("/logout", status_code=204)
async def logout(payload: LogoutRequest) -> None:
    await auth_service.revoke_refresh_token(payload.refresh_token)


@router.get("/me", response_model=UserPublic)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserPublic:
    return UserPublic(id=str(user.id), email=user.email, full_name=user.full_name, role=user.role)


@router.post("/ws-ticket", response_model=WsTicketResponse)
async def ws_ticket(user: Annotated[User, Depends(get_current_user)]) -> WsTicketResponse:
    """Normal Authorization-header auth in, a short-lived single-use ticket
    out - see services/ws_tickets.py's module docstring for why this exists.
    The frontend calls this right before opening `/ws/plans/{plan_id}` and
    passes the ticket as `?ticket=`, instead of putting the real access
    token in that URL.
    """
    ticket = await issue_ws_ticket(str(user.id))
    return WsTicketResponse(ticket=ticket)
