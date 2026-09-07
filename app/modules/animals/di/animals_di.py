"""DI providers for the animals slice (composition root).

The :func:`get_animals_port` provider is the seam between FastAPI
request handlers and the hexagonal
:class:`~app.modules.animals.ports.AnimalsPort` abstraction.

The InsForge adapter implementation was deleted in issue #668; until a
real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands (tracked as the follow-up), the provider yields a stub
that raises :class:`NotImplementedError` on every method call.

It is wired into the request handlers that depend on ``AnimalsPort``
(list/detail migrated in PR-A.2a; search/edit in PR-A.2b) and the foster
assignment gate.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from app.modules.animals.adapters.stubs.animals_stub import StubAnimalsPort
from app.modules.animals.ports.animals_port import AnimalsPort


def get_animals_port(request: Request) -> Iterator[AnimalsPort]:
    """FastAPI dependency yielding the per-request :class:`AnimalsPort`.

    Returns the :class:`StubAnimalsPort` placeholder until a real
    ``LocalPostgresExecutor``-backed adapter lands (issue #6').
    The stub raises :class:`NotImplementedError` on every method so the
    runtime fails loud per route.
    """
    del request  # unused — kept for FastAPI DI signature compatibility.
    yield StubAnimalsPort()


__all__ = ["get_animals_port"]
