"""Composition root — Cesiones slice DI.

Wires ``CesionesPort`` to ``CesionesLocalBackendAdapter``.
Mirrors ``app.modules.animals.di.animals_di.get_animals_port`` exactly:
a sync generator that reads the pooled AuthUsersPort from request state
and yields a fresh adapter per request.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.data_access import SqlExecutor
from app.modules.cesiones.adapters.local_backend.cesiones_local_backend_adapter import (
    CesionesLocalBackendAdapter,
)
from app.modules.cesiones.ports.cesiones_port import CesionesPort


def get_cesiones_port(
    request: Request,
) -> Iterator[CesionesPort]:
    """Yield a ``CesionesPort`` wired to an LocalBackend-backed adapter.

    Reads the pooled :class:`~app.core.local_backend.AuthUsersPort` from
    ``request.app.state.sql_executor`` (managed by the app lifespan).
    Yields a fresh adapter per request so the route layer is decoupled
    from the concrete adapter.
    """
    client: SqlExecutor = request.app.state.sql_executor
    adapter = CesionesLocalBackendAdapter(client)
    yield adapter


__all__ = ["get_cesiones_port"]
