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

from app.modules.animals.adapters.insforge.animals_insforge_adapter import (
    AnimalsInsforgeAdapter,
)
from app.modules.animals.ports.animals_port import AnimalsPort


def get_animals_port(request: Request) -> Iterator[AnimalsPort]:
    """FastAPI dependency yielding the per-request :class:`AnimalsPort`.

    Resolves the pooled :class:`~app.core.insforge.InsForgeClient`
    from ``app.state.insforge_client`` and wraps it in a fresh
    adapter.
    """
    client = request.app.state.insforge_client
    adapter = AnimalsInsforgeAdapter(client, storage=client)
    yield adapter


__all__ = ["get_animals_port"]
