"""FastAPI ``Depends`` wiring for the OAuth login-flow port.

The :func:`get_oauth_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`OAuthPort` abstraction.
Each request gets a fresh :class:`OAuthPort` bound to the pooled
:class:`~app.core.local_backend.AuthUsersPort` the application
lifespan already owns.

The provider is intentionally NOT wired into :mod:`app.main` by
this slice: the existing caller (``app.core.auth_flow``) continues
to use the legacy ``register_auth_flow_routes`` factory, which
constructs the adapter inside the route handler via the shim
(see the ``app.core.auth_flow`` re-export commit). A future
slice (or a follow-up to this one) wires the provider into the
request handlers that want the typed :class:`OAuthPort` directly.

Rule §22 (SQL/service separation): the adapter is constructed inside
the ``Depends`` provider, not inside the route, so the route stays a
one-liner. The shared ``request.app.state.sql_executor`` lookup and
the lazy-test fallback live in
:func:`app.core.di._yield_local_backend_port.yield_local_backend_port`.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.local_backend.oauth_local_backend_adapter import (
    LocalBackendOAuthAdapter,
)
from app.core.di._yield_local_backend_port import yield_local_backend_port
from app.core.ports.oauth_port import OAuthPort


def get_oauth_port(request: Request) -> Iterator[OAuthPort]:
    """Yield the per-request :class:`OAuthPort` backed by LocalBackend.

    The port is the abstract surface the use cases depend on. The
    concrete adapter (LocalBackend) is hidden behind this dependency so
    the route layer does not import any LocalBackend-shaped import.
    """
    return yield_local_backend_port(
        request, lambda client: LocalBackendOAuthAdapter(client)
    )


__all__ = ["get_oauth_port"]
