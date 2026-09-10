"""FastAPI ``Depends`` wiring for the OAuth login-flow port.

The :func:`get_oauth_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`OAuthPort` abstraction.
Each request gets a fresh :class:`OAuthPort` bound to the pooled
:class:`~app.core.local_backend.AuthUsersPort` the application
lifespan already owns.

Rule §22 (SQL/service separation): the adapter is constructed inside
the ``Depends`` provider, not inside the route, so the route stays a
one-liner. The shared ``request.app.state.sql_executor`` lookup and
the lazy-test fallback live in
:func:`app.core.di._yield_local_backend_port.yield_local_backend_port`.

Resolution order (mirrors :func:`app.core.di.auth_di.get_auth_users_port`):

1. ``request.app.state._oauth_port`` — set by tests to inject a fake.
2. ``app.state.sql_executor`` — production path via the application lifespan.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.local_backend.oauth_local_backend_adapter import (
    LocalBackendOAuthAdapter,
)
from app.core.config import get_settings
from app.core.di._yield_local_backend_port import yield_local_backend_port
from app.core.ports.oauth_port import OAuthPort

# Module-level lazy singleton so the httpx.Client connection pool is
# reused across requests in the same worker.
_oauth_adapter: LocalBackendOAuthAdapter | None = None


def get_oauth_port(request: Request) -> Iterator[OAuthPort]:
    """Yield the per-request :class:`OAuthPort` backed by LocalBackend.

    The port is the abstract surface the use cases depend on. The
    concrete adapter (LocalBackend) is hidden behind this dependency so
    the route layer does not import any LocalBackend-shaped import.

    Test override path: when ``request.app.state._oauth_port`` is set
    (typically by a test fixture), the dependency yields that fake
    verbatim instead of constructing a real LocalBackend adapter. This
    is the seam the ``tests/test_auth_flow.py::fake_insforge`` fixture
    uses to drive the OAuth routes without hitting the real backend.

    Implementation note: the legacy shape used
    ``return yield_local_backend_port(...)`` which — under PEP 380 —
    returned the inner generator as the ``StopIteration.value`` rather
    than yielding from it. The unit tests in
    ``tests/test_oauth_slice.py`` and ``tests/test_local_backend_di.py``
    exercise the dependency with a manual ``next(dependency)`` call, so
    we use ``yield from`` to actually yield the inner adapter.
    """
    oauth_port = getattr(request.app.state, "_oauth_port", None)
    if oauth_port is not None:
        yield oauth_port
        return

    yield from yield_local_backend_port(
        request, lambda client: LocalBackendOAuthAdapter(client)
    )


def _build_oauth_adapter() -> LocalBackendOAuthAdapter:
    """Build a standalone OAuth adapter for the test OAuth callback."""
    settings = get_settings()
    # Derive base URL from google_redirect_uri (e.g.
    # "http://127.0.0.1:8000/auth/callback" -> "http://127.0.0.1:8000")
    redirect = settings.google_redirect_uri
    base_url = redirect[: redirect.rfind("/auth/callback")]
    return LocalBackendOAuthAdapter(base_url)


__all__ = ["get_oauth_port", "_build_oauth_adapter"]
