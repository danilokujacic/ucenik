"""Tests for core/password_strength.py and its wiring into
api/users.py's CreateUserRequest/UpdateUserRequest (docs/security-
hardening.md item 14) - and, just as important, that api/auth.py's
LoginRequest never gained the same check.
"""

import pytest

from tests.conftest import auth_headers, login
from ucenik.core.password_strength import validate_password_strength
from ucenik.enum.user_role import UserRole


def test_short_password_is_rejected():
    with pytest.raises(ValueError, match="at least"):
        validate_password_strength("short1")


def test_common_password_is_rejected_even_if_long_enough():
    with pytest.raises(ValueError, match="too common"):
        validate_password_strength("password123")


def test_long_uncommon_password_is_accepted():
    validate_password_strength("correct-horse-battery-staple")  # must not raise


async def test_create_user_rejects_a_short_password(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.post(
        "/admin/users",
        json={"email": "new@x.com", "password": "short1", "full_name": "New", "role": "student"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 422


async def test_admin_password_reset_rejects_a_common_password(client, make_user):
    await make_user("admin@x.com", UserRole.ADMIN)
    target = await make_user("teacher@x.com", UserRole.TEACHER)
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.patch(
        f"/admin/users/{target.id}",
        json={"password": "password123"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 422


async def test_updating_a_user_without_touching_password_is_unaffected(client, make_user):
    """Omitting `password` entirely must not trigger the validator at all -
    UpdateUserRequest.password defaults to None, and the field_validator
    is a no-op for None (see core/password_strength.py's wiring)."""
    await make_user("admin@x.com", UserRole.ADMIN)
    target = await make_user("teacher@x.com", UserRole.TEACHER, full_name="Old Name")
    tokens = await login(client, "admin@x.com", "password123")

    response = await client.patch(
        f"/admin/users/{target.id}",
        json={"full_name": "New Name"},
        headers=auth_headers(tokens),
    )

    assert response.status_code == 200


async def test_login_has_no_password_strength_check(client, make_user):
    """A weak stored password (e.g. one created before this rule existed)
    must still be able to log in - the strength check only ever gates
    *setting* a password, never verifying one."""
    await make_user("weak@x.com", UserRole.TEACHER, password="weak")

    response = await client.post("/auth/login", json={"email": "weak@x.com", "password": "weak"})

    assert response.status_code == 200
