"""Dependency injection for the voluntarios slice (AGENTS.md §18).

Provides :func:`get_voluntarios_port`, the FastAPI dependency that wires the
LocalBackend adapter into the :class:`VoluntariosPort` Protocol. Only this
module knows both the Protocol and the concrete adapter. The executor comes
from ``request.app.state.sql_executor`` and satisfies :class:`SqlExecutor`.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.data_access import SqlExecutor
from app.modules.voluntarios.adapters.local_backend.voluntarios_local_backend_adapter import (
    VoluntariosLocalBackendAdapter,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def get_voluntarios_port(request: Request) -> Iterator[VoluntariosPort]:
    """FastAPI dependency yielding a per-request :class:`VoluntariosPort`.

    Resolves the pooled :class:`~app.core.local_backend.db.LocalPostgresExecutor`
    from ``request.app.state`` and wraps it in a fresh
    :class:`VoluntariosLocalBackendAdapter`.
    The adapter is stateless beyond the injected executor, so a fresh
    instance per request is cheap.
    """
    client: SqlExecutor = request.app.state.sql_executor
    yield VoluntariosLocalBackendAdapter(client)


__all__ = ["get_voluntarios_port"]
