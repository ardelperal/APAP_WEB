"""Use case: look up a user by id (active or inactive)."""
from __future__ import annotations

from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.auth_port import AuthUsersPort


def get_user_by_id(
    port: AuthUsersPort,
    user_id: str,
) -> AuthorizedUser | None:
    """Return the user with this id, or ``None`` if not found.

    Unlike :func:`get_user_by_email` this query is NOT filtered by
    ``activo = true`` — it is used by
    :func:`deactivate_authorized_user` to disambiguate "user not
    found" from "last-developer guard fired" after the conditional
    UPDATE returns zero rows.
    """
    return port.get_user_by_id(user_id)
