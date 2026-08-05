"""DI providers for the auth users slice.

The :func:`get_auth_users_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`AuthUsersPort` abstraction.
Each request gets a fresh :class:`InsForgeAuthUsersAdapter` bound to
the pooled :class:`~app.core.insforge.InsForgeClient` the application
lifespan already owns (so the adapter's instantiation is cheap — no
I/O, no connection management — and the lifespan's client teardown
is unaffected).

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

    Resolves the pooled :class:`~app.core.insforge.InsForgeClient`
    from ``app.state.insforge_client`` (created by the application
    lifespan) and wraps it in a fresh adapter. The adapter is
    stateless and cheap to construct; no resource ownership is
    transferred, so the ``yield`` (rather than ``return``) is purely
    for FastAPI's dependency-injection contract symmetry, not for
    cleanup.
    """
    client = request.app.state.insforge_client
    adapter = InsForgeAuthUsersAdapter(client)
    yield adapter
