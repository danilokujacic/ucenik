/**
 * Frontend mirror of backend core/password_strength.py - same rule, same
 * minimum length, same blocklist (docs/security-hardening.md item 14).
 * Registration/account-creation only - never wired into the login form.
 *
 * This is UX only, not a security control on its own: a request can always
 * skip the frontend entirely, so the backend validator (api/users.py's
 * CreateUserRequest/UpdateUserRequest) is the actual enforcement boundary
 * regardless of what this returns. The two are kept in sync deliberately -
 * a frontend rule laxer than the backend's just means a user hits a
 * server-side rejection anyway; stricter means the frontend rejects things
 * the backend would accept, which is just wrong friction for no reason.
 */

const MIN_LENGTH = 10;

// Keep this list identical to core/password_strength.py's _COMMON_PASSWORDS.
const COMMON_PASSWORDS = new Set([
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
]);

/** Returns an error message if `password` doesn't meet the minimum bar,
 * or null if it's fine. */
export function passwordStrengthError(password: string): string | null {
  if (password.length < MIN_LENGTH) {
    return `Password must be at least ${MIN_LENGTH} characters long.`;
  }
  if (COMMON_PASSWORDS.has(password.toLowerCase())) {
    return "That password is too common - choose something less guessable.";
  }
  return null;
}
