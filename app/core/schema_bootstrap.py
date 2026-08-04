"""Shared execution primitive for replay-safe schema bootstrap statements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.logging import log_safe


@dataclass(frozen=True, slots=True)
class SqlStatement:
    """One bootstrap SQL statement and its optional positional parameters."""

    query: str
    params: list[Any] | None = None


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
    Protocol (issue #259) rather than the concrete ``InsForgeClient``,
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
