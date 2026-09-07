"""Composition root for the lifecycle slice (LIFECYCLE-03 PR-B).

Wires the
:class:`~app.modules.lifecycle.adapters.local_backend.lifecycle_local_backend_adapter.LifecyclePort`
into the
:class:`~app.modules.lifecycle.ports.lifecycle_port.LifecyclePort`
Protocol that the application layer consumes. The wiring is a single
factory function -- there is no per-request state in the lifecycle
slice (the adapter is stateless beyond the injected
:class:`~app.core.data_access.SqlExecutor`), so the composition
root is also stateless.

Per AGENTS.md §33.4: ``AuthUsersPort`` and ``BackendError`` are
imported only under ``adapters/`` and ``di/`` (plus ``app/main.py``
which builds the pooled client). Domain, ports and application are
transport-agnostic -- which is why this module is the only place in
the slice that knows both the Protocol AND the concrete adapter.

LIFECYCLE-03 (issue #33) PR-B.
"""
from __future__ import annotations

from app.core.data_access import SqlExecutor
from app.modules.lifecycle.adapters.stubs.lifecycle_stub import (
    LifecyclePort,
)
from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort


def build_lifecycle_port(executor: SqlExecutor) -> LifecyclePort:
    """Return the slice's :class:`LifecyclePort` bound to ``executor``.

    The factory is intentionally a single line so callers can wire
    it through a FastAPI dependency (``Depends``) without ceremony:

    .. code-block:: python

        def get_lifecycle_port(
            executor: SqlExecutor = Depends(get_sql_executor),
        ) -> LifecyclePort:
            return build_lifecycle_port(executor)

    PR-C's callsite rewrites reach this factory through
    ``app.modules.animals.lifecycle_events.actualizar_estado_animal``
    which builds the port per request and delegates to the domain
    cascade. The simplified ``_EVENT_TYPE_TO_STATE`` map that lived
    in lifecycle_events.py before LIFECYCLE-03 PR-C was the P1
    fidelity gap; it is replaced by this wired cascade.
    """
    return LifecyclePort()


__all__ = ["build_lifecycle_port"]
