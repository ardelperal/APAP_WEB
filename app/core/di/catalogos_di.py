"""FastAPI ``Depends`` wiring for the catalog (reference-data) port.

Slice 1 of the hexagonal refactor:
``refactor/hexagonal-slice-catalogos``. The DI helper hides the
concrete :class:`LocalPostgresExecutor` from the application layer — routes
and use cases depend on :class:`CatalogosPort`, never on the concrete
backend.

The LocalBackend adapter implementation was deleted in issue #666; until a
real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands (tracked as the follow-up), the provider yields a stub
that raises :class:`NotImplementedError` on every method call.

Pattern (mirrors :func:`app.core.auth_dependencies.get_local_postgres_executor_dep`):

1. Yield the per-request port bound to the request-scoped
   :class:`SqlExecutor`. Production: the pool of executor lives on
   ``app.state.sql_executor`` (the lifespan creates one
   :class:`LocalPostgresExecutor` and reuses its underlying ``httpx.Client``
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

from app.core.adapters.stubs.catalogos_stub import StubCatalogosPort
from app.core.ports.catalogos_port import CatalogosPort


def get_catalogos_port(request: Request) -> Iterator[CatalogosPort]:
    """Yield the per-request :class:`CatalogosPort` stub.

    Returns the :class:`StubCatalogosPort` placeholder until a real
    ``LocalPostgresExecutor``-backed adapter lands (issue #4b').
    The stub raises :class:`NotImplementedError` on every method so the
    runtime fails loud per route.
    """
    del request  # unused — kept for FastAPI DI signature compatibility.
    yield StubCatalogosPort()


__all__ = ["get_catalogos_port"]
