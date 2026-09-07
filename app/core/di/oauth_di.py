"""FastAPI ``Depends`` wiring for the OAuth login-flow port.

The :func:`get_oauth_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`OAuthPort` abstraction.
The InsForge adapter implementation was deleted in issue #666; until a
real :class:`~app.core.local_backend.oauth_google`-backed adapter
lands (tracked as the follow-up), the provider yields a stub that
raises :class:`NotImplementedError` on every method call.

The provider is intentionally NOT wired into :mod:`app.main` by
this slice: the existing caller (``app.core.auth_flow``) continues
to use the legacy ``register_auth_flow_routes`` factory, which
constructs the adapter inside the route handler via the shim
(see the ``app.core.auth_flow`` re-export commit). A future
slice (or a follow-up to this one) wires the provider into the
request handlers that want the typed :class:`OAuthPort`
directly.
"""


from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.stubs.oauth_stub import StubOAuthPort
from app.core.ports.oauth_port import OAuthPort


def get_oauth_port(request: Request) -> Iterator[OAuthPort]:
    """Yield the per-request :class:`OAuthPort` stub.

    Returns the :class:`StubOAuthPort` placeholder until a real
    ``local_backend.oauth_google``-backed adapter lands (issue #4b').
    The stub raises :class:`NotImplementedError` on every method so the
    runtime fails loud per route.
    """
    del request  # unused — kept for FastAPI DI signature compatibility.
    yield StubOAuthPort()


__all__ = ["get_oauth_port"]
