"""Login, token refresh, logout - see api/auth.py for the request/response
shapes and the route handlers that call these.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from ucenik.core.config import settings
from ucenik.core.security import TokenType, create_token, decode_token, verify_password
from ucenik.errors.service import (
    InvalidCredentialsError,
    InvalidTokenError,
    NotFoundError,
    TokenExpiredError,
    parse_object_id,
)
from ucenik.models.auth_sessions import AuthSession
from ucenik.models.users import User

ACCESS_TOKEN_EXPIRE = timedelta(minutes=settings.jwt_access_token_expire_minutes)
REFRESH_TOKEN_EXPIRE = timedelta(days=settings.jwt_refresh_token_expire_days)


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


async def authenticate(email: str, password: str) -> User:
    user = await User.find_one(User.email == email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("invalid email or password")
    return user


async def issue_tokens(user: User) -> tuple[str, str, int]:
    """Returns (access_token, refresh_token, expires_in_seconds)."""
    access_token = create_token(str(user.id), TokenType.ACCESS, ACCESS_TOKEN_EXPIRE)

    jti = str(uuid4())
    now = datetime.now(UTC)
    refresh_token = create_token(str(user.id), TokenType.REFRESH, REFRESH_TOKEN_EXPIRE, extra_claims={"jti": jti})
    await AuthSession(jti=jti, user_id=str(user.id), expires_at=now + REFRESH_TOKEN_EXPIRE).insert()

    return access_token, refresh_token, int(ACCESS_TOKEN_EXPIRE.total_seconds())


async def refresh_access_token(refresh_token: str) -> tuple[str, int]:
    """Returns (access_token, expires_in_seconds)."""
    token_payload = await _decode_refresh_token(refresh_token)

    session = await AuthSession.find_one(AuthSession.jti == token_payload["jti"])
    if session is None or session.revoked:
        raise InvalidTokenError("refresh token has been revoked")

    user = await User.get(parse_object_id("User", token_payload["sub"]))
    if user is None:
        raise NotFoundError("User", token_payload["sub"])

    access_token = create_token(str(user.id), TokenType.ACCESS, ACCESS_TOKEN_EXPIRE)
    return access_token, int(ACCESS_TOKEN_EXPIRE.total_seconds())


async def revoke_refresh_token(refresh_token: str) -> None:
    token_payload = await _decode_refresh_token(refresh_token)
    session = await AuthSession.find_one(AuthSession.jti == token_payload["jti"])
    if session is not None:
        session.revoked = True
        await session.save()
