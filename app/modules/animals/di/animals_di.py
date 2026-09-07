"""DI providers for the animals slice (composition root).

The :func:`get_animals_port` provider is the seam between FastAPI
request handlers and the hexagonal
:class:`~app.modules.animals.ports.AnimalsPort` abstraction.

It is wired into the request handlers that depend on ``AnimalsPort``
(list/detail migrated in PR-A.2a; search/edit in PR-A.2b) and the foster
assignment gate.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.modules.animals.adapters.local_backend.animals_local_backend_adapter import (
    AnimalsLocalBackendAdapter,
)
from app.modules.animals.ports.animals_port import AnimalsPort


def get_animals_port(request: Request) -> Iterator[AnimalsPort]:
    """FastAPI dependency yielding the per-request :class:`AnimalsPort`.

    Resolves the pooled :class:`~app.core.local_backend.AuthUsersPort`
    from ``app.state.sql_executor`` and wraps it in a fresh
    adapter.
    """
    client = request.app.state.sql_executor
    adapter = AnimalsLocalBackendAdapter(client=client, storage=None)
    yield adapter


__all__ = ["get_animals_port"]
