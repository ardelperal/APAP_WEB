"""Composition root for the materiales slice (issue #752, PR 4 of 5).

Defines :func:`get_materiales_port`, the FastAPI dependency that
yields the per-request :class:`MaterialesPort`. The route layer
calls ``Depends(get_materiales_port)`` instead of constructing the
adapter inline — keeps the adapter lifetime in one place and lets
the routes stay transport-agnostic.

Pattern source: ``app.core.di.catalogos_di`` (the canonical
``yield_local_backend_port`` user). The shared helper hides the
``app.state.sql_executor`` lookup and the ASGI-test fallback;
this module only owns the port-specific type hint and adapter.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.di._yield_local_backend_port import yield_local_backend_port
from app.modules.materiales.adapters.local_backend.materiales_local_backend_adapter import (
    LocalBackendMaterialesAdapter,
)
from app.modules.materiales.ports.materiales_port import MaterialesPort


def get_materiales_port(request: Request) -> Iterator[MaterialesPort]:
    """Yield the per-request :class:`MaterialesPort` backed by LocalBackend.

    Wraps the lifespan-cached ``SqlExecutor`` in a fresh
    :class:`LocalBackendMaterialesAdapter`. The adapter holds no
    resources of its own (the executor is owned by the lifespan),
    so no per-request cleanup runs in the ``finally`` seam.

    Implementation note: the legacy shape was
    ``return yield_local_backend_port(...)`` which — under PEP 380 —
    returned the inner generator as the ``StopIteration.value``
    rather than yielding from it. The unit tests in
    ``tests/test_materiales_di_provider.py`` exercise the dependency
    with a manual ``next(dependency)`` call, so we use ``yield from``
    to actually yield the inner adapter. Same trap documented in
    ``app.core.di.oauth_di.get_oauth_port``.
    """
    yield from yield_local_backend_port(
        request, lambda client: LocalBackendMaterialesAdapter(client)
    )


__all__ = ["get_materiales_port"]
