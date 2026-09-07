"""DI providers for the auth users slice.

The :func:`get_auth_users_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`AuthUsersPort` abstraction.
The LocalBackend adapter implementation was deleted in issue #666; until a
real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands (tracked as the follow-up), the provider yields a stub
that raises :class:`NotImplementedError` on every method call.

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

from app.core.adapters.stubs.auth_users_stub import StubAuthUsersPort
from app.core.ports.auth_port import AuthUsersPort


def get_auth_users_port(
    request: Request,
) -> Iterator[AuthUsersPort]:
    """FastAPI dependency yielding the per-request :class:`AuthUsersPort`.

    Returns the :class:`StubAuthUsersPort` placeholder until a real
    ``LocalPostgresExecutor``-backed adapter lands (issue #4b').
    The stub raises :class:`NotImplementedError` on every method so the
    runtime fails loud per route.
    """
    del request  # unused — kept for FastAPI DI signature compatibility.
    yield StubAuthUsersPort()
