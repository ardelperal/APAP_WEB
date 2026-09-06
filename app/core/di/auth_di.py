"""DI providers for the auth users slice.

The :func:`get_auth_users_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`AuthUsersPort` abstraction.
Each request gets a fresh :class:`InsForgeAuthUsersAdapter` bound to
the shared :class:`~app.core.local_backend.db.LocalPostgresExecutor`
the application lifespan owns (see commit e3f3bd0 for the migration
from :class:`InsForgeClient` to ``LocalPostgresExecutor``; the legacy
``InsForgeClient`` is deprecated as of commit f68b4cc).

The provider is intentionally NOT wired into :mod:`app.main` by this
slice: the existing callers (``app.core.auth_dependencies``,
``app.core.auth_flow``, ``app.core.admin_handlers``) continue to use
the legacy ``app.core.auth`` shim, which creates an adapter per call
inside the shim. A future slice (or a follow-up to this one) wires
the provider into the request handlers that want the typed
``AuthUsersPort`` directly.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.insforge.auth_insforge_adapter import (
    InsForgeAuthUsersAdapter,
)
from app.core.ports.auth_port import AuthUsersPort


def get_auth_users_port(
    request: Request,
) -> Iterator[AuthUsersPort]:
    """FastAPI dependency yielding the per-request :class:`AuthUsersPort`.

    Resolves the shared :class:`~app.core.local_backend.db.LocalPostgresExecutor`
    from ``app.state.sql_executor`` (set by the application lifespan
    in commit e3f3bd0) and wraps it in a fresh adapter. The adapter
    is stateless and cheap to construct; no resource ownership is
    transferred, so the ``yield`` (rather than ``return``) is purely
    for FastAPI's dependency-injection contract symmetry, not for
    cleanup.
    """
    client = request.app.state.sql_executor
    adapter = InsForgeAuthUsersAdapter(client)
    yield adapter
