"""Contract tests for the shared idempotent schema-bootstrap primitive."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.schema_bootstrap import SqlStatement, run_idempotent_sql


class _RecordingClient:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.calls: list[tuple[str, list[Any] | None]] = []
        self.fail_at = fail_at

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append((query, params))
        if self.fail_at == len(self.calls) - 1:
            raise RuntimeError("database unavailable")
        return []


def test_run_idempotent_sql_executes_statements_in_declared_order() -> None:
    client = _RecordingClient()
    statements = (
        SqlStatement("CREATE TABLE first"),
        SqlStatement("INSERT INTO first VALUES ($1)", ["seed"]),
        SqlStatement("CREATE TABLE second"),
    )

    run_idempotent_sql(client, statements, step_name="catalogs")

    assert client.calls == [
        ("CREATE TABLE first", None),
        ("INSERT INTO first VALUES ($1)", ["seed"]),
        ("CREATE TABLE second", None),
    ]


def test_run_idempotent_sql_stops_and_propagates_on_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingClient(fail_at=1)
    logged: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.core.schema_bootstrap.log_safe",
        lambda event, **fields: logged.append((event, fields)),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        run_idempotent_sql(
            client,
            (
                SqlStatement("CREATE TABLE first"),
                SqlStatement("CREATE TABLE broken"),
                SqlStatement("CREATE TABLE never_reached"),
            ),
            step_name="domain",
        )

    assert client.calls == [
        ("CREATE TABLE first", None),
        ("CREATE TABLE broken", None),
    ]
    assert logged == [
        (
            "schema_bootstrap.failed",
            {
                "step_name": "domain",
                "statement_index": 1,
                "error_type": "RuntimeError",
            },
        )
    ]


def test_run_idempotent_sql_accepts_an_empty_statement_sequence() -> None:
    client = _RecordingClient()

    run_idempotent_sql(client, (), step_name="nothing-to-bootstrap")

    assert client.calls == []
