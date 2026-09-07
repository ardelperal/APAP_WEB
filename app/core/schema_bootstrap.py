"""Backward-compat shim for the schema-bootstrap slice.

This module keeps the legacy import surface
(``from app.core.schema_bootstrap import SqlStatement,
run_idempotent_sql``) alive while the canonical hexagonal
implementation lives under :mod:`app.core.application.schema_bootstrap`
and :mod:`app.core.adapters.local_backend.schema_bootstrap_local_backend_adapter`.

The canonical "via port" use case is
:func:`app.core.application.schema_bootstrap.run_idempotent_sql.run_idempotent_sql`,
which depends on the :class:`SchemaBootstrapPort` Protocol rather than
on a concrete backend client. Future slices will migrate
``app/main.py`` and the cold-start modules
(``ensure_catalogos``, ``ensure_schema_and_seed``) to that port-typed
use case; until then the legacy ``client``-typed signature below
remains the working entry point for tests and the lifespan.

Historical context — non-contract: the original implementation (issue
#32, LIFECYCLE-02 + later hardening) lives here unchanged so that
``tests/test_schema_bootstrap.py`` continues to monkeypatch
``app.core.schema_bootstrap.log_safe`` and observe the exact failure
log shape.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.data_access import SqlExecutor
from app.core.logging import log_safe
from app.core.ports.schema_bootstrap_port import SqlStatement


def run_idempotent_sql(
    client: SqlExecutor,
    statements: Sequence[SqlStatement],
    *,
    step_name: str,
) -> None:
    """Execute replay-safe statements in order and fail fast on errors.

    Idempotence remains a property of each supplied SQL statement (for
    example ``IF NOT EXISTS`` or ``ON CONFLICT DO NOTHING``). This helper
    centralizes ordered execution and safe failure telemetry without
    swallowing or translating the original database exception.

    The ``client`` parameter is typed as the :class:`SqlExecutor`
    Protocol (issue #259) rather than the concrete ``LocalPostgresExecutor``,
    so this primitive stays backend-agnostic and can drive the future
    legacy-Access adapter without a separate bootstrap path.
    """
    for statement_index, statement in enumerate(statements):
        try:
            client.execute_sql(statement.query, statement.params)
        except Exception as exc:
            log_safe(
                "schema_bootstrap.failed",
                step_name=step_name,
                statement_index=statement_index,
                error_type=type(exc).__name__,
            )
            raise


__all__ = ["SqlStatement", "run_idempotent_sql"]
