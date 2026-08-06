from datetime import datetime, timezone

from beanie import Document, Indexed
from pydantic import Field


class AuthSession(Document):
    """One row per issued refresh token. Lets /auth/logout actually revoke a
    refresh token before its natural expiry, unlike a bare stateless JWT.
    Mongo's TTL index (`expireAfterSeconds=0` on `expires_at`) auto-deletes
    rows once the token would have expired anyway.
    """

    jti: Indexed(str, unique=True)
    user_id: Indexed(str)
    expires_at: Indexed(datetime, expireAfterSeconds=0)
    revoked: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "auth_sessions"
