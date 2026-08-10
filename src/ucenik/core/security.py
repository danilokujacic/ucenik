from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ucenik.core.config import settings
from ucenik.errors.service import InvalidTokenError, NotFoundError, TokenExpiredError, parse_object_id
from ucenik.models.users import User

ALGORITHM = "HS256"

bearer_scheme = HTTPBearer()


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> User:
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError("access token expired")
    except jwt.InvalidTokenError:
        raise InvalidTokenError("invalid access token")

    if payload.get("type") != TokenType.ACCESS.value:
        raise InvalidTokenError("expected an access token")

    user = await User.get(parse_object_id("User", payload["sub"]))
    if user is None:
        raise NotFoundError("User", payload["sub"])

    return user
