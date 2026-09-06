"""FastAPI ``Depends`` wiring for the OAuth login-flow port.

The :func:`get_oauth_port` provider is the seam between FastAPI
request handlers and the hexagonal :class:`OAuthPort` abstraction.
Each request gets a fresh :class:`InsForgeOAuthAdapter` bound to
the pooled :class:`~app.core.insforge.InsForgeClient` the
application lifespan already owns (so the adapter's instantiation
is cheap — no I/O, no connection management — and the lifespan's
client teardown is unaffected).

The provider is intentionally NOT wired into :mod:`app.main` by
this slice: the existing caller (``app.core.auth_flow``) continues
to use the legacy ``register_auth_flow_routes`` factory, which
constructs the adapter inside the route handler via the shim
(see the ``app.core.auth_flow`` re-export commit). A future
slice (or a follow-up to this one) wires the provider into the
request handlers that want the typed :class:`OAuthPort`
directly.

Pattern (mirrors :func:`app.core.di.catalogos_di.get_catalogos_port`):

1. Yield the per-request port bound to the request-scoped
   :class:`InsForgeClient`. Production: the client lives on
   ``app.state.sql_executor`` (the lifespan creates one
   and reuses its underlying ``httpx.Client`` across requests).
   The adapter is cheap to construct (no I/O), so building it
   per request is fine.
2. On ``AttributeError`` (a lightweight ASGI test transport that
   does not run the lifespan), lazily create the same client.
   This preserves the ergonomic ``app.dependency_overrides``
   pattern in tests.

Rule §2 (resources that own ``.close()`` use ``yield``): the
client is owned by the lifespan, not the dependency — this
helper does not close it on exit. The ``try/finally`` block
is the seam a future multi-worker adapter could use to
release per-worker resources.
"""


from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.insforge.oauth_insforge_adapter import (
    InsForgeOAuthAdapter,
)
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.ports.oauth_port import OAuthPort


def get_oauth_port(request: Request) -> Iterator[OAuthPort]:
    """Yield the per-request :class:`OAuthPort` backed by InsForge.

    The port is the abstract surface the use cases depend on. The
    concrete adapter (InsForge) is hidden behind this dependency so
    the route layer does not import any InsForge-shaped import.

    The lifespan stores the pooled :class:`InsForgeClient` on
    ``app.state.sql_executor``; that client is reused across
    requests to amortize the underlying ``httpx.Client`` connection
    pool. A lightweight ASGI test transport that does not run the
    lifespan falls back to a lazily-created client so the same
    dependency is usable in unit tests without overriding the
    lifespan.

    The yielded value is the :class:`OAuthPort` interface, not
    the concrete adapter — routes and use cases should not need to
    import :class:`InsForgeOAuthAdapter` directly.
    """
    try:
        client = request.app.state.sql_executor
    except AttributeError:
        # Lazy fallback for ASGI test transports that skip the lifespan.
        # Production always initializes this state in
        # ``app.main.lifespan``; this branch keeps the dep usable in
        # tests that exercise FastAPI without ``LifespanMiddleware``.
        settings = get_settings()
        client = InsForgeClient(
            settings.insforge_url,
            settings.insforge_service_key,
        )
        request.app.state.sql_executor = client
    try:
        adapter = InsForgeOAuthAdapter(client)
        yield adapter
    finally:
        # The adapter holds no resources of its own; the client is
        # owned by the lifespan and is not closed per request.
        # The blank ``finally`` is the seam a future per-worker
        # adapter (e.g. a Redis-backed rate limit) would use to
        # release per-worker resources without changing the route
        # layer.
        pass


__all__ = ["get_oauth_port"]
