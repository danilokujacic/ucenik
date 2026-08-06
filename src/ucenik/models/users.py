from datetime import datetime, timezone

from beanie import Document, Indexed
from pydantic import EmailStr, Field

from ucenik.enum.user_role import UserRole


class User(Document):
    email: Indexed(EmailStr, unique=True)
    password_hash: str
    full_name: str
    role: UserRole
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"
