"""Use case: list every authorized user (active + inactive) for the admin panel."""
from __future__ import annotations

from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.auth_port import AuthUsersPort


def list_authorized_users(
    port: AuthUsersPort,
) -> list[AuthorizedUser]:
    """Return all users (active and inactive) for the admin panel."""
    return port.list_authorized_users()
