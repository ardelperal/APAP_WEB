"""Shared LocalBackend port DI helper (issue #641 slice).

``app/core/di/{catalogos,oauth,schema_bootstrap}_di.py`` are three
near-identical FastAPI dependencies that:
1. Resolve the request-scoped ``SqlExecutor`` from
   ``request.app.state.sql_executor``.
2. Lazily fall back to a freshly-built ``LocalPostgresExecutor`` when
   the lifespan did not run (ASGI test transports).
3. Construct the per-port adapter from the client and ``yield`` it.

The duplicate boilerplate (try/except AttributeError, the local-DB
fallback that caches the executor on ``app.state``, the empty
``try/finally: pass`` seam) is the entire reason this helper exists —
the per-port file keeps only its own type hint, the adapter import,
and the public ``Depends`` provider function.

Rule §2 (resources that own ``.close()`` use ``yield``) and §22
(SQL/service separation): the executor is owned by the lifespan, not
the dependency, so the helper never closes it on exit. The blank
``finally`` is the seam a future per-worker adapter would use to
release per-worker resources without changing the route layer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TypeVar

from fastapi import Request

from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor

_PortT = TypeVar("_PortT")


def yield_local_backend_port(
    request: Request,
    adapter_factory: Callable[[LocalPostgresExecutor], _PortT],
) -> Iterator[_PortT]:
    """Yield a per-request port adapter backed by the request-scoped executor.

    The lifespan stores the pooled :class:`SqlExecutor` on
    ``app.state.sql_executor``; that client is reused across requests
    to amortize the underlying ``httpx.Client`` connection pool. A
    lightweight ASGI test transport that does not run the lifespan
    falls back to a lazily-created client so the same dependency is
    usable in unit tests without overriding the lifespan.

    ``adapter_factory`` wires the executor into the concrete adapter
    (typically a ``LocalBackend<Port>Adapter``); the helper does not
    know or care which port it produces.
    """
    try:
        client = request.app.state.sql_executor
    except AttributeError:
        # Lazy fallback for ASGI test transports that skip the lifespan.
        # Production always initializes this state in
        # ``app.main.lifespan``; this branch keeps the dep usable in
        # tests that exercise FastAPI without ``LifespanMiddleware``.
        settings = get_settings()
        client = LocalPostgresExecutor(
            settings.local_db_url,
            settings.local_db_schema or None,
        )
        request.app.state.sql_executor = client
    try:
        yield adapter_factory(client)
    finally:
        # The adapter holds no resources of its own; the executor is
        # owned by the lifespan and is not closed per request.
        # The blank ``finally`` is the seam a future per-worker
        # adapter (e.g. a Redis-backed cache) would use to release
        # per-worker resources without changing the route layer.
        pass


__all__ = ["yield_local_backend_port"]
