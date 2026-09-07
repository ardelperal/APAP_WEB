"""Backward-compat shim for the pre-Phase-1 ``app.core.auth`` public surface.

The auth users module has been migrated to a hexagonal slice:

  - :mod:`app.core.domain.auth`       — entities (``AuthorizedUser``, ``Rol``)
  - :mod:`app.core.ports.auth_port`   — :class:`AuthUsersPort` Protocol
  - :mod:`app.core.application.auth`  — use cases (one per file)
  - :mod:`app.core.adapters.insforge.auth_insforge_adapter` — InsForge adapter
  - :mod:`app.core.di.auth_di`        — FastAPI DI provider

This module preserves the pre-Phase-1 API so the existing callers
(``app.core.auth_dependencies``, ``app.core.auth_flow``,
``app.core.admin_handlers``, ``app.modules.foster.routes``, ...) keep
working without a signature change. Every shim function:

1. Accepts the legacy first argument (``client: SqlExecutor`` — the
   LocalPostgresExecutor satisfies the Protocol structurally).
2. Constructs a fresh :class:`StubAuthUsersPort` from the
   client (cheap, no I/O).
3. Delegates to the new use case.
4. Converts the use case's :class:`~app.core.domain.auth.user.AuthorizedUser`
   back to the dict shape the legacy callers expect via
   :meth:`AuthorizedUser.to_dict`.
5. Re-raises the use case's ``ValueError`` unchanged.

The shim is the ONLY place in ``app/`` that exposes the legacy
``(client, ...) -> dict`` API. New code SHOULD import the use
cases directly (``from app.core.application.auth.add_authorized_user
import add_authorized_user``) and pass the port from the DI
provider. The shim stays for one migration window so the
:mod:`app.core.auth_dependencies.require_authorized_user` and
:mod:`app.core.auth_flow.callback` rewrites can land as their own
slices (each will move from the dict API to the typed port).

This replaces the rejected layered-port attempt (PR #413) with a
full hexagonal split. The shim is the only Layer-2-bridge the new
shape requires; everything below it (domain / ports / application /
adapter) is pure hexagonal.
"""

from __future__ import annotations

from typing import Any

from app.core.adapters.stubs.auth_users_stub import StubAuthUsersPort
from app.core.application.auth._has_other_active_developers import (
    has_other_active_developers as _has_other_active_developers_use_case,
)
from app.core.application.auth.add_authorized_user import (
    add_authorized_user as _add_authorized_user_use_case,
)
from app.core.application.auth.deactivate_authorized_user import (
    deactivate_authorized_user as _deactivate_authorized_user_use_case,
)
from app.core.application.auth.ensure_schema_and_seed import (
    ensure_schema_and_seed as _ensure_schema_and_seed_use_case,
)
from app.core.application.auth.get_user_by_email import (
    get_user_by_email as _get_user_by_email_use_case,
)
from app.core.application.auth.get_user_by_id import (
    get_user_by_id as _get_user_by_id_use_case,
)
from app.core.application.auth.list_authorized_users import (
    list_authorized_users as _list_authorized_users_use_case,
)
from app.core.config import Settings
from app.core.data_access import SqlExecutor
from app.core.roles import Rol

# Derivado del enum (regla 4 del code quality: una sola fuente de verdad
# por concepto de dominio). NO hardcodear; cualquier nuevo rol se agrega
# a ``Rol`` y se refleja automáticamente. Sigue viviendo aquí (no en
# ``app.core.roles``) para no añadir dependencias al módulo del enum.
VALID_ROLES: frozenset[str] = frozenset(r.value for r in Rol)

# Re-export ``Rol`` because the foster module imports it from
# ``app.core.auth`` (pre-Phase-1 path). The domain layer's
# :mod:`app.core.domain.auth.rol` re-exports the same enum; future
# slices SHOULD migrate foster/routes.py to import from
# ``app.core.domain.auth.rol`` directly.
__all__ = [
    "Rol",
    "VALID_ROLES",
    "add_authorized_user",
    "deactivate_authorized_user",
    "ensure_schema_and_seed",
    "get_user_by_email",
    "get_user_by_id",
    "list_authorized_users",
]


def _adapter(client: SqlExecutor) -> StubAuthUsersPort:
    """Build a fresh :class:`StubAuthUsersPort`.

    The InsForge adapter was deleted in issue #666; until a real
    :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
    adapter lands (tracked as the follow-up), the stub raises
    :class:`NotImplementedError` on every method call so the runtime
    fails loud per route.

    The ``client`` parameter is preserved for signature compatibility
    with the previous ``StubAuthUsersPort``; the stub does not
    consume it (the stub is stateless and has no resources of its own).
    """
    del client  # unused — kept for signature compatibility.
    return StubAuthUsersPort()


def _to_dict_or_none(user):
    """Return ``user.to_dict()`` if user is not None, else None."""
    return user.to_dict() if user is not None else None


def ensure_schema_and_seed(
    client: SqlExecutor,
    settings: Settings,
) -> None:
    """Create the table (idempotent) and seed the bootstrap admin.

    Backward-compat wrapper around
    :func:`app.core.application.auth.ensure_schema_and_seed.ensure_schema_and_seed`.

    The ``settings.initial_admin_email`` flag still drives whether
    the bootstrap admin is seeded (the use case short-circuits on
    an empty value). The actual DDL + INSERT live in the InsForge
    adapter.
    """
    _ensure_schema_and_seed_use_case(_adapter(client), settings)


def get_user_by_email(
    client: SqlExecutor,
    email: str,
) -> dict[str, Any] | None:
    """Return the active user with this email as a dict, or ``None``.

    Backward-compat wrapper around
    :func:`app.core.application.auth.get_user_by_email.get_user_by_email`.
    The dict shape matches the pre-Phase-1 return type so
    ``require_authorized_user`` and ``auth_flow.callback`` keep
    doing ``row["rol"]`` and ``row["id"]`` lookups.
    """
    return _to_dict_or_none(_get_user_by_email_use_case(_adapter(client), email))


def list_authorized_users(
    client: SqlExecutor,
) -> list[dict[str, Any]]:
    """Return every user (active + inactive) as a list of dicts.

    Backward-compat wrapper around
    :func:`app.core.application.auth.list_authorized_users.list_authorized_users`.
    The admin table view in ``admin.html`` iterates over the list and
    reads ``row["email"]``, ``row["rol"]``, ``row["activo"]``,
    ``row["id"]`` — all of which the
    :meth:`AuthorizedUser.to_dict` projection includes.
    """
    return [user.to_dict() for user in _list_authorized_users_use_case(_adapter(client))]


def add_authorized_user(
    client: SqlExecutor,
    email: str,
    role: str,
    added_by: str,
) -> dict[str, Any]:
    """Insert a new authorized user and return the row as a dict.

    Backward-compat wrapper around
    :func:`app.core.application.auth.add_authorized_user.add_authorized_user`.

    Note: the legacy kwarg is ``role=`` (not ``rol=``); this shim
    keeps the historical name so
    :func:`app.core.admin_handlers._add_user_or_error` does not need
    to change. The use case takes the typed :class:`Rol` enum; the
    shim constructs it from the ``str`` here.
    """
    user = _add_authorized_user_use_case(_adapter(client), email, Rol(role), added_by)
    return user.to_dict()


def get_user_by_id(
    client: SqlExecutor,
    user_id: str,
) -> dict[str, Any] | None:
    """Return the user with this id as a dict, or ``None`` if not found.

    Backward-compat wrapper around
    :func:`app.core.application.auth.get_user_by_id.get_user_by_id`.
    """
    return _to_dict_or_none(_get_user_by_id_use_case(_adapter(client), user_id))


def deactivate_authorized_user(
    client: SqlExecutor,
    user_id: str,
) -> dict[str, Any] | None:
    """Mark the user as inactive and return the row as a dict.

    Backward-compat wrapper around
    :func:`app.core.application.auth.deactivate_authorized_user.deactivate_authorized_user`.
    ``ValueError`` propagates unchanged for the "user not found" /
    "last developer" / "unexpected" cases the admin route catches
    in :mod:`app.core.admin_handlers`.
    """
    return _to_dict_or_none(
        _deactivate_authorized_user_use_case(_adapter(client), user_id)
    )


def _has_other_active_developers(
    client: SqlExecutor,
    exclude_user_id: str,
) -> bool:
    """Return True if at least one other active developer exists.

    Backward-compat wrapper around
    :func:`app.core.application.auth._has_other_active_developers.has_other_active_developers`.
    The use case dispatches to the adapter's private
    ``_has_other_active_developers`` method via ``getattr``; this
    shim builds the adapter from the legacy client.
    """
    return _has_other_active_developers_use_case(_adapter(client), exclude_user_id)
