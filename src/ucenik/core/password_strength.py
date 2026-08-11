"""Password strength validation (docs/security-hardening.md item 14) -
registration/account-creation only, never login. api/users.py's
CreateUserRequest and UpdateUserRequest (admin-initiated password resets go
through the same field) both call this; api/auth.py's LoginRequest must
never gain this check - it verifies a password against an existing stored
hash, there's no "new password being set" to have an opinion about there.

Rule: NIST 800-63B-style - length over classic complexity rules. Modern
guidance favors a longer minimum with no forced character-class
requirements (1 digit + 1 uppercase + ...) over the older complexity-rule
approach, which mostly optimizes for passwords like "Password1!" -
technically compliant with a complexity rule, still trivially guessable. A
small common-password blocklist catches the most obvious well-known weak
choices a length-only rule alone would otherwise wave through.
"""

_MIN_LENGTH = 10

# Not exhaustive - the well-known top offenders, cheap to check as a plain
# set membership test, catches the most obvious "that's not actually a
# real password" cases a length-only rule alone would miss. A full
# breached-password-list check (e.g. Have I Been Pwned's range API) is the
# more thorough version of this same idea - out of scope here on purpose,
# this is meant to stay a fast, dependency-free, no-network-call check.
_COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "12345678",
    "123456789",
    "1234567890",
    "qwerty123",
    "qwertyuiop",
    "letmein123",
    "welcome123",
    "iloveyou1",
    "admin1234",
    "abc123456",
    "password!",
    "changeme123",
}


def validate_password_strength(password: str) -> None:
    """Raises ValueError - which a Pydantic field_validator turns into a
    normal 422 field error (frontend's lib/api/client.ts already parses
    that shape, no new error-handling path needed) - if `password` doesn't
    meet the minimum bar.
    """
    if len(password) < _MIN_LENGTH:
        raise ValueError(f"password must be at least {_MIN_LENGTH} characters long")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("password is too common - choose something less guessable")
