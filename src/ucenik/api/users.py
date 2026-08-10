from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr

from ucenik.core.permissions import require_role
from ucenik.core.security import get_current_user
from ucenik.enum.user_role import UserRole
from ucenik.models.users import User
from ucenik.services import users as users_service

router = APIRouter(prefix="/admin/users", tags=["admin"])
students_router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    role: UserRole | None = None
    password: str | None = None  # admin-initiated reset - see services/users.py's update_user docstring


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole


def _to_public(user: User) -> UserPublic:
    return UserPublic(id=str(user.id), email=user.email, full_name=user.full_name, role=user.role)


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: CreateUserRequest,
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserPublic:
    user = await users_service.create_user(payload.email, payload.password, payload.full_name, payload.role)
    return _to_public(user)


@router.get("", response_model=list[UserPublic])
async def list_users(_admin: Annotated[User, Depends(require_role(UserRole.ADMIN))]) -> list[UserPublic]:
    users = await users_service.list_users()
    return [_to_public(u) for u in users]


@router.patch("/{user_id}", response_model=UserPublic)
async def update_user(
    payload: UpdateUserRequest,
    target: Annotated[User, Depends(users_service.get_user_or_404)],
    _admin: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserPublic:
    user = await users_service.update_user(target, payload.full_name, payload.role, payload.password)
    return _to_public(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    target: Annotated[User, Depends(users_service.get_user_or_404)],
    admin: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> None:
    await users_service.delete_user(admin, target)


class StudentLookupPublic(BaseModel):
    id: str
    email: EmailStr
    full_name: str


@students_router.get("/students/lookup", response_model=StudentLookupPublic)
async def lookup_student_by_email(
    email: EmailStr,
    _requester: Annotated[User, Depends(require_role(UserRole.TEACHER, UserRole.ADMIN))],
) -> StudentLookupPublic:
    student = await users_service.lookup_student_by_email(email)
    return StudentLookupPublic(id=str(student.id), email=student.email, full_name=student.full_name)


class QuotaPublic(BaseModel):
    used_tokens: int
    limit: int
    resets_at: datetime


# On students_router despite the name (its prefix is /users, which is what
# matters here) - this endpoint is for any authenticated user, not just
# students, unlike the lookup endpoint above it.
@students_router.get("/me/quota", response_model=QuotaPublic)
async def my_quota(user: Annotated[User, Depends(get_current_user)]) -> QuotaPublic:
    used, limit, resets_at = await users_service.get_quota_summary(str(user.id))
    return QuotaPublic(used_tokens=used, limit=limit, resets_at=resets_at)
