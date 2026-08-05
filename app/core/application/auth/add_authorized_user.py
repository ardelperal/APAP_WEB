"""Use case: insert a new authorized user.

Domain rules owned by this use case (not by the adapter):

- **Email normalization + format validation** — empty / malformed
  emails are rejected with ``ValueError`` at the application boundary,
  not the transport layer.
- **Role validation** — the supplied ``rol`` must be a member of the
  :class:`~app.core.domain.auth.rol.Rol` enum (rule 4 — single source
  of truth per domain concept; the database has no CHECK constraint
  on ``rol`` so this use case is the sole gate).
- **Pre-insert duplicate detection** — a ``port.get_user_by_email``
  pre-check catches the common case (operator typed an email that
  already exists) before the INSERT, producing a clean ``ValueError``
  with a user-facing message.
- **Race-condition duplicate detection** — when two parallel INSERTs
  slip past the pre-check, the transport translates 23505 /
  duplicate-key bodies into
  :class:`~app.core.data_access.DuplicateKeyError`, which this use
  case translates into the same ``ValueError`` contract. This is the
  Protocol-level catch introduced by the foundation work (issue #259)
  and the active fix for issue #277 (the old code inspected
  ``InsForgeError.body`` for the substring ``"duplicate"``).
- **Auth-cache invalidation** — issue #143. A prior deactivate may
  have cached a deny for this email; re-adding must take effect on
  the next request, not after the TTL.
"""
from __future__ import annotations

from app.core.auth_cache import invalidate_auth
from app.core.auth_helpers import normalize_email, validate_email_format
from app.core.data_access import DuplicateKeyError
from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.auth_port import AuthUsersPort


def add_authorized_user(
    port: AuthUsersPort,
    email: str,
    rol: Rol,
    added_by: str,
) -> AuthorizedUser:
    """Insert a new authorized user.

    Raises ``ValueError`` on:
    - empty / malformed email (from ``validate_email_format``)
    - ``rol`` not in :class:`Rol`
    - duplicate canonical email (pre-check or race-condition INSERT)
    """
    normalized = normalize_email(email)
    validate_email_format(normalized)
    valid_roles = {r.value for r in Rol}
    if rol.value not in valid_roles:
        raise ValueError(
            f"invalid role: {rol.value!r}; must be one of {sorted(valid_roles)}"
        )
    # Pre-insert duplicate check (cheap path — avoids a unique-violation race).
    # Uses ``port.check_email_taken`` (narrow SELECT) so the test spy can
    # distinguish this call from the auth-revalidation call in
    # require_authorized_user, which uses ``port.get_user_by_email`` (full
    # SELECT with ``rol,``). See AuthUsersPort.check_email_taken for the
    # full rationale.
    if port.check_email_taken(normalized):
        raise ValueError(f"email already authorized: {normalized!r}")
    try:
        user = port.add_authorized_user(normalized, rol, added_by)
    except DuplicateKeyError as exc:
        # Defense in depth — the adapter translates 23505 / duplicate-key
        # bodies to DuplicateKeyError before this layer sees them; any
        # other envelope shape is a genuine transport failure that the
        # global DataAccessError handler still owns.
        raise ValueError(f"email already authorized: {normalized!r}") from exc  # noqa: TRY003
    # Issue #143: a prior deactivate may have cached a deny for this email;
    # re-adding must take effect on the next request, not after the TTL.
    invalidate_auth(normalized)
    return user
