"""FastAPI ``Depends`` wiring for the schema-bootstrap port.

Slice of the hexagonal refactor. The DI helper hides the concrete
:class:`AuthUsersPort` from the application layer — domain code
depends on :class:`SchemaBootstrapPort`, never on the concrete
backend.

Rule §22 (SQL/service separation): the adapter is constructed inside
the ``Depends`` provider, not inside the route, so the route stays a
one-liner. The shared ``request.app.state.sql_executor`` lookup and
the lazy-test fallback live in
:func:`app.core.di._yield_local_backend_port.yield_local_backend_port`.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.adapters.local_backend.schema_bootstrap_local_backend_adapter import (
    LocalBackendSchemaBootstrapAdapter,
)
from app.core.di._yield_local_backend_port import yield_local_backend_port
from app.core.ports.schema_bootstrap_port import SchemaBootstrapPort


def get_schema_bootstrap_port(
    request: Request,
) -> Iterator[SchemaBootstrapPort]:
    """Yield the per-request :class:`SchemaBootstrapPort` backed by LocalBackend.

    The port is the abstract surface the use cases depend on. The
    concrete adapter (LocalBackend) is hidden behind this dependency so
    the use-case layer does not import any LocalBackend-shaped import.
    """
    return yield_local_backend_port(
        request, lambda client: LocalBackendSchemaBootstrapAdapter(client)
    )


__all__ = ["get_schema_bootstrap_port"]
