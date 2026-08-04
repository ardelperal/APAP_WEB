"""Use case: look up an active authorized user by canonical email.

Normalizes the email to its canonical form (stripped + lowercased)
before the lookup, so that mixed-case variants resolve to the same
canonical row (issue #278).
"""
from __future__ import annotations

from app.core.auth_helpers import normalize_email
from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.auth_port import AuthUsersPort


def get_user_by_email(
    port: AuthUsersPort,
    email: str,
) -> AuthorizedUser | None:
    """Return the active user with this email, or ``None``.

    The email is normalized to its canonical form before the lookup;
    case-variant duplicates that pre-existed the normalization are
    still caught by the adapter's case-insensitive WHERE clause as a
    defense-in-depth.
    """
    normalized = normalize_email(email)
    return port.get_user_by_email(normalized)
