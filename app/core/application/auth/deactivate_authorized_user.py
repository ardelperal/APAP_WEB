"""Use case: mark a user as inactive.

Domain rules owned by this use case (not by the adapter):

- **Cache invalidation** — issue #143. The deactivated email's
  cached verdict (positive or negative) must be unreachable on the
  next request. The cache is keyed by email; the use case reads the
  ``email`` from the deactivated row returned by the port and
  invalidates explicitly.
- **Domain error translation** — the adapter raises Protocol-level
  errors (``UserNotFoundError``, ``LastActiveDeveloperError``,
  ``UnexpectedDeactivateError``) and this use case translates them
  into the ``ValueError`` contract the legacy ``app.core.auth``
  callers (admin routes, lifespan bootstrap) expect.

The atomic conditional UPDATE inside the adapter is what enforces
the last-developer guard at the SQL level (issue #279): the
``SET activo = false WHERE id = $1 AND (rol <> 'developer' OR
<other developer exists>)`` clause causes the UPDATE to return zero
rows when deactivating the last developer, and the adapter then
disambiguates via ``port.get_user_by_id`` plus the private
``_has_other_active_developers`` helper. That disambiguation is
adapter-internal; this use case only sees the resulting domain
exception.
"""
from __future__ import annotations

from app.core.application.auth._domain_errors import (
    LastActiveDeveloperError,
    UnexpectedDeactivateError,
    UserNotFoundError,
)
from app.core.auth_cache import invalidate_auth
from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.auth_port import AuthUsersPort


def deactivate_authorized_user(
    port: AuthUsersPort,
    user_id: str,
) -> AuthorizedUser:
    """Mark the user as inactive and return the deactivated row.

    Raises ``ValueError`` on:
    - user not found
    - the last active developer (cannot leave APAP without a developer
      to access ``/admin``)
    - any other unexpected zero-row outcome (defensive)
    """
    try:
        user = port.deactivate_authorized_user(user_id)
    except UserNotFoundError as exc:
        raise ValueError(f"user not found: {user_id!r}") from exc  # noqa: TRY003
    except LastActiveDeveloperError as exc:
        raise ValueError("cannot deactivate the last active developer") from exc  # noqa: TRY003
    except UnexpectedDeactivateError as exc:
        raise ValueError(
            f"deactivate failed unexpectedly for user {user_id!r}"
        ) from exc  # noqa: TRY003
    # Issue #143: invalidate the cache so revocation takes effect on the
    # user's next request rather than after the TTL.
    invalidate_auth(user.email)
    return user
