"""Composition root — Cesiones slice DI.

Wires ``CesionesPort`` -> ``CesionesInsforgeAdapter`` -> InsForge.
Mirrors ``app.modules.animals.di.animals_di.get_animals_port`` exactly:
a sync generator that reads the pooled InsForgeClient from request state
and yields a fresh adapter per request.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.core.data_access import SqlExecutor
from app.modules.cesiones.adapters.insforge.cesiones_insforge_adapter import (
    CesionesInsforgeAdapter,
)
from app.modules.cesiones.ports.cesiones_port import CesionesPort


def get_cesiones_port(
    request: Request,
) -> Iterator[CesionesPort]:
    """Yield a ``CesionesPort`` wired to an InsForge-backed adapter.

    Reads the pooled :class:`~app.core.insforge.InsForgeClient` from
    ``request.app.state.insforge_client`` (managed by the app lifespan).
    Yields a fresh adapter per request so the route layer is decoupled
    from the concrete adapter.
    """
    client: SqlExecutor = request.app.state.sql_executor
    adapter = CesionesInsforgeAdapter(client)
    yield adapter


__all__ = ["get_cesiones_port"]
