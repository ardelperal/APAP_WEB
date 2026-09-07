"""Stub adapter for ``LifecyclePort`` — pending local-backend implementation.

Replaces the deleted
:class:`app.modules.lifecycle.adapters.local_backend.lifecycle_local_backend_adapter.LocalBackendLifecycleAdapter`.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

Affected operations (raise until the real adapter lands):

- :func:`app.modules.lifecycle.application.derive_state.derive_state`
  (delegated to :meth:`LifecyclePort.calculate_state`).
- :func:`app.modules.lifecycle.application.persist_state.persist_animal_state`
  (delegated to :meth:`LifecyclePort.persist_animal_state`).

See issue #6' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort


class StubLifecyclePort(LifecyclePort):
    """Placeholder :class:`LifecyclePort` whose every method raises."""

    def calculate_state(self, *args, **kwargs):
        raise NotImplementedError(
            "LifecyclePort.calculate_state: pending local-backend adapter, see #6'"
        )

    def persist_animal_state(self, *args, **kwargs):
        raise NotImplementedError(
            "LifecyclePort.persist_animal_state: pending local-backend adapter, see #6'"
        )


__all__ = ["StubLifecyclePort"]
