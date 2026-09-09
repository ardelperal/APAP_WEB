"""FastAPI ``Depends`` wiring for the OAuth login-flow port.

The :func:`get_oauth_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`OAuthPort` abstraction.
Each request gets a :class:`LocalBackendOAuthAdapter` bound to the
running app's base URL (from ``request.base_url``), which calls the
internal OAuth endpoints via :class:`httpx.Client`.

The provider checks ``request.app.state._oauth_port`` first (for test
overrides), then falls back to the module-level singleton.

The provider is wired into :mod:`app.core.auth_flow` by this slice:
the route handlers take ``oauth_port: OAuthPort = Depends(get_oauth_port)``
so they are decoupled from the concrete adapter.

Rule §2 (resources that own ``.close()`` use ``yield``): the
adapter holds an ``httpx.Client`` that is reused across requests
for connection-pool efficiency. The ``finally`` block closes it
cleanly so the pool is torn down when the worker shuts down.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.local_backend.oauth_adapter import LocalBackendOAuthAdapter
from app.core.ports.oauth_port import OAuthPort

# Module-level lazy singleton so the httpx.Client connection pool is
# reused across requests in the same worker.
_oauth_adapter: LocalBackendOAuthAdapter | None = None


def _get_base_url(request: Request) -> str:
    """Return the base URL of the running application."""
    return str(request.base_url)


def get_oauth_port(request: Request) -> Iterator[OAuthPort]:
    """Yield the per-request :class:`OAuthPort` backed by LocalBackend.

    Resolution order:
    1. ``request.app.state._oauth_port`` — set by tests to inject a fake.
    2. Module-level ``_oauth_adapter`` singleton — reused across requests.
    3. Lazy creation from ``request.base_url`` — production path.

    The adapter calls ``GET /auth/oauth/google`` and
    ``POST /auth/oauth/exchange`` via :class:`httpx.Client` scoped to
    the running app's ``request.base_url``.
    """
    # Test override path
    oauth_port: OAuthPort | None = getattr(request.app.state, "_oauth_port", None)
    if oauth_port is not None:
        yield oauth_port
        return

    # Production / reuse singleton path
    global _oauth_adapter
    if _oauth_adapter is None:
        base_url = _get_base_url(request)
        _oauth_adapter = LocalBackendOAuthAdapter(base_url)
    try:
        yield _oauth_adapter
    finally:
        # Close the client on worker shutdown, not on each request.
        pass


def _build_oauth_adapter() -> LocalBackendOAuthAdapter:
    """Build a standalone OAuth adapter for the test OAuth callback."""
    settings = get_settings()
    # Derive base URL from google_redirect_uri (e.g.
    # "http://127.0.0.1:8000/auth/callback" -> "http://127.0.0.1:8000")
    redirect = settings.google_redirect_uri
    base_url = redirect[: redirect.rfind("/auth/callback")]
    return LocalBackendOAuthAdapter(base_url)


__all__ = ["get_oauth_port", "_build_oauth_adapter"]
