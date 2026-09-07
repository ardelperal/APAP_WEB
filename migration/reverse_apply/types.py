"""Reverse-apply type definitions + exception hierarchy.

PR6 typed-exception hierarchy mirror of ``migration.apply``. Lives in
its own module so the orchestrator and the per-row / shadow /
lifecycle helpers can share the same Protocol + base exception
without circular imports through the orchestrator.

Backwards-compat: ``migration.apply_reverse`` re-exports
``ReverseApplyError`` and ``ReverseSyncStateRollbackError`` so the
existing test surface (``migration.apply_reverse.ReverseApplyError``
references) keeps working without change.
"""

from __future__ import annotations

from typing import Any, Protocol

from migration import MigrationError


class SqlExecutor(Protocol):
    """Structural type for the web client passed to ``apply_web_to_legacy``.

    Mirrors the surface ``LocalPostgresExecutor.execute_sql`` exposes, plus
    the private ``apap-photos`` bucket accessors that the bootstrap
    uses. The :class:`FakeLocalBackend` test fixture satisfies the
    protocol by duck typing.
    """

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_bucket(self, bucket_name: str) -> dict[str, Any] | None: ...

    def ensure_bucket(
        self, bucket_name: str, *, is_public: bool = False
    ) -> dict[str, Any]: ...


class ReverseApplyError(MigrationError):
    """Base class for typed reverse-apply failures.

    Mirror of the forward applier's typed-exception hierarchy. PR6
    ships one concrete subtype (``ReverseSyncStateRollbackError``)
    used by the transactional sync_state update; new subtypes land
    alongside future reverse-only failure modes (e.g. DLQ-style
    retry on a single legacy write that retries N times before
    failing the run).
    """


class ReverseSyncStateRollbackError(ReverseApplyError):
    """``sync_state.json`` could not be advanced after a successful legacy write.

    The legacy write already committed (the operator cannot roll back
    the .accdb transaction via the seam); the operator gets a
    categorical line that points to the runbook and the row's audit
    log. The forward applier's MSACCESS / partial-apply / drift
    branches are unchanged — the reverse path shares the same
    dataset and the same per-table ``tables[table].last_sync_at``
    cursor.
    """


__all__ = [
    "ReverseApplyError",
    "ReverseSyncStateRollbackError",
    "SqlExecutor",
]
