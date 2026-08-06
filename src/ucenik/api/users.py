from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr
from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError

from ucenik.core.permissions import require_role
from ucenik.core.security import hash_password
from ucenik.enum.user_role import UserRole
from ucenik.errors.persistence import translate_duplicate_key
from ucenik.errors.service import DuplicateResourceError
from ucenik.models.users import User

router = APIRouter(prefix="/admin/users", tags=["admin"])


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserPublic:
    """Admin-only: there is no self-service /auth/register. Accounts are
    provisioned here and handed to the user out of band.
    """
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    try:
        await user.insert()
    except MongoDuplicateKeyError as exc:
        raise DuplicateResourceError("User", payload.email) from translate_duplicate_key("User", exc)

    return UserPublic(id=str(user.id), email=user.email, full_name=user.full_name, role=user.role)
