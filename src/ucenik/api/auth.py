from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr

from ucenik.api.users import UserPublic
from ucenik.core.config import settings
from ucenik.core.security import TokenType, create_token, decode_token, get_current_user, verify_password
from ucenik.errors.service import (
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    TokenExpiredError,
    parse_object_id,
)
from ucenik.models.auth_sessions import AuthSession
from ucenik.models.users import User

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_TOKEN_EXPIRE = timedelta(minutes=settings.jwt_access_token_expire_minutes)
REFRESH_TOKEN_EXPIRE = timedelta(days=settings.jwt_refresh_token_expire_days)


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


async def _decode_refresh_token(token: str) -> dict:
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("refresh token expired")
    except jwt.InvalidTokenError:
        raise InvalidTokenError("invalid refresh token")

    if payload.get("type") != TokenType.REFRESH.value:
        raise InvalidTokenError("expected a refresh token")

    return payload


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    user = await User.find_one(User.email == payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise InvalidCredentialsError("invalid email or password")

    access_token = create_token(str(user.id), TokenType.ACCESS, ACCESS_TOKEN_EXPIRE)

    jti = str(uuid4())
    now = datetime.now(timezone.utc)
    refresh_token = create_token(str(user.id), TokenType.REFRESH, REFRESH_TOKEN_EXPIRE, extra_claims={"jti": jti})
    await AuthSession(jti=jti, user_id=str(user.id), expires_at=now + REFRESH_TOKEN_EXPIRE).insert()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=int(ACCESS_TOKEN_EXPIRE.total_seconds()),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(payload: RefreshRequest) -> AccessTokenResponse:
    token_payload = await _decode_refresh_token(payload.refresh_token)

    session = await AuthSession.find_one(AuthSession.jti == token_payload["jti"])
    if session is None or session.revoked:
        raise InvalidTokenError("refresh token has been revoked")

    user = await User.get(parse_object_id("User", token_payload["sub"]))
    if user is None:
        raise NotFoundError("User", token_payload["sub"])

    access_token = create_token(str(user.id), TokenType.ACCESS, ACCESS_TOKEN_EXPIRE)
    return AccessTokenResponse(access_token=access_token, expires_in=int(ACCESS_TOKEN_EXPIRE.total_seconds()))


@router.post("/logout", status_code=204)
async def logout(payload: LogoutRequest) -> None:
    token_payload = await _decode_refresh_token(payload.refresh_token)
    session = await AuthSession.find_one(AuthSession.jti == token_payload["jti"])
    if session is not None:
        session.revoked = True
        await session.save()


@router.get("/me", response_model=UserPublic)
async def me(user: Annotated[User, Depends(get_current_user)]) -> UserPublic:
    return UserPublic(id=str(user.id), email=user.email, full_name=user.full_name, role=user.role)
