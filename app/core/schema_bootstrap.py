"""Shared execution primitive for replay-safe schema bootstrap statements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.insforge import InsForgeClient
from app.core.logging import log_safe


@dataclass(frozen=True, slots=True)
class SqlStatement:
    """One bootstrap SQL statement and its optional positional parameters."""

    query: str
    params: list[Any] | None = None


def run_idempotent_sql(
    client: InsForgeClient,
    statements: Sequence[SqlStatement],
    *,
    step_name: str,
) -> None:
    """Execute replay-safe statements in order and fail fast on errors.

    Idempotence remains a property of each supplied SQL statement (for
    example ``IF NOT EXISTS`` or ``ON CONFLICT DO NOTHING``). This helper
    centralizes ordered execution and safe failure telemetry without
    swallowing or translating the original database exception.
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
