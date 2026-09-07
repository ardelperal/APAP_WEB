"""Stub adapter for ``LifecyclePort`` — pending local-backend implementation.

Replaces the deleted
:class:`app.modules.lifecycle.adapters.stubs.lifecycle_stub.legacy_LocalBackendLifecycleAdapter`.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

See issue #6' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort


class StubLifecyclePort(LifecyclePort):
    """Placeholder :class:`LifecyclePort` whose every method raises."""

    def run_idempotent_sql(self, *args, **kwargs):
        raise NotImplementedError(
            "LifecyclePort.run_idempotent_sql: pending local-backend adapter, see #6'"
        )

    def calculate_state(self, *args, **kwargs):
        raise NotImplementedError(
            "LifecyclePort.calculate_state: pending local-backend adapter, see #6'"
        )

    def persist_animal_state(self, *args, **kwargs):
        raise NotImplementedError(
            "LifecyclePort.persist_animal_state: pending local-backend adapter, see #6'"
        )

    def ensure_domain_schema(self, *args, **kwargs):
        raise NotImplementedError(
            "LifecyclePort.ensure_domain_schema: pending local-backend adapter, see #6'"
        )


__all__ = ["LifecyclePort"]
