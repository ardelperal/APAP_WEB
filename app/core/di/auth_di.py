"""DI providers for the auth users slice.

The :func:`get_auth_users_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`AuthUsersPort` abstraction.
Each request gets a fresh :class:`LocalBackendAuthUsersAdapter` bound to
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

from app.core.local_backend.auth_adapter import (
    LocalBackendAuthUsersAdapter,
)
from app.core.ports.auth_port import AuthUsersPort


def get_auth_users_port(
    request: Request,
) -> Iterator[AuthUsersPort]:
    """FastAPI dependency yielding the per-request :class:`AuthUsersPort`.

    Resolution order:
    1. ``request.app.state._auth_users_port`` — set by tests to inject a fake.
    2. ``app.state.sql_executor`` — production path via the application lifespan.

    The adapter is stateless and cheap to construct; no resource ownership is
    transferred, so the ``yield`` (rather than ``return``) is purely
    for FastAPI's dependency-injection contract symmetry, not for cleanup.
    """
    # Test override path
    auth_port = getattr(request.app.state, "_auth_users_port", None)
    if auth_port is not None:
        yield auth_port
        return

    # Production path: resolve SqlExecutor from app.state
    client = request.app.state.sql_executor
    adapter = LocalBackendAuthUsersAdapter(client)
    yield adapter
