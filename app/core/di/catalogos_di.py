"""FastAPI ``Depends`` wiring for the catalog (reference-data) port.

Slice 1 of the hexagonal refactor:
``refactor/hexagonal-slice-catalogos``. The DI helper hides the
concrete :class:`AuthUsersPort` from the application layer — routes
and use cases depend on :class:`CatalogosPort`, never on the concrete
backend.

Pattern (mirrors :func:`app.core.auth_dependencies.get_local_postgres_executor_dep`):

1. Yield the per-request port bound to the request-scoped
   :class:`SqlExecutor`. Production: the pool of executor lives on
   ``app.state.sql_executor`` (the lifespan creates one
   :class:`AuthUsersPort` and reuses its underlying ``httpx.Client``
   across requests). The adapter is cheap to construct (no I/O), so
   building it per request is fine.
2. On AttributeError (a lightweight ASGI test transport that does
   not run the lifespan), lazily create the same client. This
   preserves the ergonomic ``app.dependency_overrides`` pattern in
   tests.

Rule §2 (resources that own ``.close()`` use ``yield``): the executor
is owned by the lifespan, not the dependency — this helper does not
close it on exit. The ``try/finally`` block is the seam a future
multi-worker adapter could use to release per-worker resources.

Rule §22 (SQL/service separation): the adapter is constructed here,
not inside the route, so the route stays a one-liner.
"""


from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.local_backend.catalogos_local_backend_adapter import (
    LocalBackendCatalogosAdapter,
)
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.ports.catalogos_port import CatalogosPort


def get_catalogos_port(request: Request) -> Iterator[CatalogosPort]:
    """Yield the per-request :class:`CatalogosPort` backed by LocalBackend.

    The port is the abstract surface the use cases depend on. The
    concrete adapter (LocalBackend) is hidden behind this dependency so
    the route layer does not import any LocalBackend-shaped import.

    The lifespan stores the pooled :class:`AuthUsersPort` on
    ``app.state.sql_executor``; that client is reused across
    requests to amortize the underlying ``httpx.Client`` connection
    pool. A lightweight ASGI test transport that does not run the
    lifespan falls back to a lazily-created client so the same
    dependency is usable in unit tests without overriding the
    lifespan.

    The yielded value is the :class:`CatalogosPort` interface, not
    the concrete adapter — routes and use cases should not need to
    import :class:`CatalogosPort` directly.
    """
    try:
        client = request.app.state.sql_executor
    except AttributeError:
        # Lazy fallback for ASGI test transports that skip the lifespan.
        # Production always initializes this state in
        # ``app.main.lifespan``; this branch keeps the dep usable in
        # tests that exercise FastAPI without ``LifespanMiddleware``.
        settings = get_settings()
        client = LocalPostgresExecutor(
            settings.local_db_url,
            settings.local_db_schema or None,
        )
        request.app.state.sql_executor = client
    try:
        adapter = LocalBackendCatalogosAdapter(client)
        yield adapter
    finally:
        # The adapter holds no resources of its own; the executor is
        # owned by the lifespan and is not closed per request.
        # The blank ``finally`` is the seam a future per-worker
        # adapter (e.g. a Redis-backed cache) would use to release
        # per-worker resources without changing the route layer.
        pass


__all__ = ["get_catalogos_port"]
