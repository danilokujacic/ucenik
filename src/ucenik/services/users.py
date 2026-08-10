"""Admin user provisioning/management, the teacher-facing student lookup,
and the "my quota" summary - see api/users.py for request/response shapes.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError

from ucenik.core.config import settings
from ucenik.core.quota import get_usage, next_reset_at
from ucenik.core.security import hash_password
from ucenik.enum.user_role import UserRole
from ucenik.errors.persistence import translate_duplicate_key
from ucenik.errors.service import DuplicateResourceError, InvalidStateError, NotFoundError, parse_object_id
from ucenik.models.auth_sessions import AuthSession
from ucenik.models.users import User


async def get_user_or_404(user_id: str) -> User:
    user = await User.get(parse_object_id("User", user_id))
    if user is None:
        raise NotFoundError("User", user_id)
    return user


async def create_user(email: str, password: str, full_name: str, role: UserRole) -> User:
    """Admin-only: there is no self-service /auth/register. Accounts are
    provisioned here and handed to the user out of band.
    """
    user = User(email=email, password_hash=hash_password(password), full_name=full_name, role=role)
    try:
        await user.insert()
    except MongoDuplicateKeyError as exc:
        raise DuplicateResourceError("User", email) from translate_duplicate_key("User", exc)
    return user


async def list_users() -> list[User]:
    return await User.find_all().to_list()


async def update_user(
    target: User,
    full_name: str | None,
    role: UserRole | None,
    password: str | None,
) -> User:
    """Covers admin-initiated password resets too (`password`) - there's no
    self-service "forgot password" flow (that would need email infra this
    project doesn't have, see docs/backlog.md item 9), but an admin can
    still set a new password for someone locked out.
    """
    if full_name is not None:
        target.full_name = full_name
    if role is not None:
        target.role = role
    if password is not None:
        target.password_hash = hash_password(password)
    target.updated_at = datetime.now(UTC)
    await target.save()
    return target


async def delete_user(admin: User, target: User) -> None:
    """Revokes the deleted user's refresh tokens (AuthSession rows) so a
    stolen/cached one can't outlive the account - their short-lived access
    token (if one's still unexpired) isn't revocable, same limitation as
    everywhere else in this codebase (AuthSession's own docstring).

    Deliberately does NOT cascade to content the user owned (subjects,
    documents, chat sessions, ...) - that's a real gap (deleting a teacher
    orphans their subjects rather than reassigning or blocking), not
    something silently glossed over; full referential-integrity handling
    here was out of scope for this pass.
    """
    if str(target.id) == str(admin.id):
        raise InvalidStateError("cannot delete your own admin account")
    await AuthSession.find(AuthSession.user_id == str(target.id)).delete()
    await target.delete()


async def lookup_student_by_email(email: str) -> User:
    """Teacher-facing lookup so enrolling a student (POST
    /subjects/{id}/enrollments) doesn't require already knowing their raw
    ObjectId - see docs/frontend-spec.md's gap list.

    Deliberately scoped to role=student only, with a minimal field set: a
    teacher shouldn't be able to use this to probe whether an arbitrary
    email belongs to some other teacher/admin account. A non-student email
    (or no match at all) gets the same 404 either way - existence isn't
    leaked outside the student population this exists to serve.
    """
    student = await User.find_one(User.email == email, User.role == UserRole.STUDENT)
    if student is None:
        raise NotFoundError("Student", email)
    return student


async def get_quota_summary(user_id: str) -> tuple[int, int, datetime]:
    """Returns (used_tokens, limit, resets_at). Was previously the *only*
    way to learn you'd hit your daily LLM token quota - a 429 mid-question/
    mid-generation, with core/quota.py's counter itself never exposed via
    any GET. See docs/backlog.md item 5.
    """
    used = await get_usage(user_id)
    return used, settings.max_quota, next_reset_at()
