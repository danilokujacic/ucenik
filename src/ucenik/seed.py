"""Seeds one demo teacher and one demo student account for local
development. There's no self-service signup and no other seeding path in
this codebase (the `ucenik` console script left over from `uv init` is just
a placeholder that prints a greeting) - without this, the only way to get
*any* account into a fresh database is a direct Mongo insert.

Idempotent: re-running updates the existing seeded users' password/name/role
rather than hitting the unique email index - safe to run again after
changing SEED_PASSWORD or as a quick "reset these two accounts" tool.

Run: `uv run ucenik-seed`
"""

import asyncio

from ucenik.core.db import close_db, init_db
from ucenik.core.security import hash_password
from ucenik.enum.user_role import UserRole
from ucenik.models import ALL_DOCUMENT_MODELS
from ucenik.models.users import User

SEED_PASSWORD = "ucenik123"

SEED_USERS = [
    {"email": "teacher@ucenik.dev", "full_name": "Demo Teacher", "role": UserRole.TEACHER},
    {"email": "student@ucenik.dev", "full_name": "Demo Student", "role": UserRole.STUDENT},
]


async def _seed() -> None:
    await init_db(document_models=ALL_DOCUMENT_MODELS)
    try:
        password_hash = hash_password(SEED_PASSWORD)
        for spec in SEED_USERS:
            existing = await User.find_one(User.email == spec["email"])
            if existing is not None:
                existing.password_hash = password_hash
                existing.full_name = spec["full_name"]
                existing.role = spec["role"]
                await existing.save()
                print(f"updated  {spec['role'].value:<8} {spec['email']}")
            else:
                await User(
                    email=spec["email"],
                    password_hash=password_hash,
                    full_name=spec["full_name"],
                    role=spec["role"],
                ).insert()
                print(f"created  {spec['role'].value:<8} {spec['email']}")
    finally:
        await close_db()

    print(f"\npassword for both: {SEED_PASSWORD}")


def run() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    run()
