"""FastAPI ``Depends`` wiring for the catalog (reference-data) port.

Slice 1 of the hexagonal refactor:
``refactor/hexagonal-slice-catalogos``. The DI helper hides the
concrete :class:`AuthUsersPort` from the application layer — routes
and use cases depend on :class:`CatalogosPort`, never on the concrete
backend.

Rule §22 (SQL/service separation): the adapter is constructed inside
the ``Depends`` provider, not inside the route, so the route stays a
one-liner. The shared ``request.app.state.sql_executor`` lookup and
the lazy-test fallback live in
:func:`app.core.di._yield_local_backend_port.yield_local_backend_port`
(this module only owns the port-specific type hint and adapter).
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.local_backend.catalogos_local_backend_adapter import (
    LocalBackendCatalogosAdapter,
)
from app.core.di._yield_local_backend_port import yield_local_backend_port
from app.core.ports.catalogos_port import CatalogosPort


def get_catalogos_port(request: Request) -> Iterator[CatalogosPort]:
    """Yield the per-request :class:`CatalogosPort` backed by LocalBackend.

    The port is the abstract surface the use cases depend on. The
    concrete adapter (LocalBackend) is hidden behind this dependency so
    the route layer does not import any LocalBackend-shaped import.
    """
    return yield_local_backend_port(
        request, lambda client: LocalBackendCatalogosAdapter(client)
    )


__all__ = ["get_catalogos_port"]
