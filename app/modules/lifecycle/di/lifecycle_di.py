"""Composition root for the lifecycle slice (LIFECYCLE-03 PR-B).

Wires a :class:`StubLifecyclePort` (pending a real
``LocalPostgresExecutor``-backed adapter in the follow-up to #668)
into the
:class:`~app.modules.lifecycle.ports.lifecycle_port.LifecyclePort`
Protocol that the application layer consumes. The LocalBackend adapter
implementation was deleted in issue #668; the stub raises
:class:`NotImplementedError` on every method call so the runtime fails
loud.

Per AGENTS.md §33.4: ``LocalPostgresExecutor`` and ``BackendError`` are
imported only under ``adapters/`` and ``di/`` (plus ``app/main.py``
which builds the pooled client). Domain, ports and application are
transport-agnostic -- which is why this module is the only place in
the slice that knows both the Protocol AND the concrete adapter.

LIFECYCLE-03 (issue #33) PR-B.
"""
from __future__ import annotations

from app.core.data_access import SqlExecutor
from app.modules.lifecycle.adapters.stubs.lifecycle_stub import StubLifecyclePort
from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort


def build_lifecycle_port(executor: SqlExecutor) -> LifecyclePort:
    """Return the slice's :class:`LifecyclePort` stub placeholder.

    The LocalBackend adapter was deleted in issue #668; until a real
    :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
    adapter lands (tracked as the follow-up), the stub raises
    :class:`NotImplementedError` on every method call so the runtime
    fails loud per route.

    The ``executor`` parameter is preserved for signature compatibility
    with the previous ``LocalBackendLifecycleAdapter``; the stub does not
    consume it (the stub is stateless and has no resources of its own).
    """
    del executor  # unused — kept for signature compatibility.
    return StubLifecyclePort()


__all__ = ["build_lifecycle_port"]
