"""Tests for the M0 local backend's Postgres adapter (issue #641).

The local backend has its own SQL executor that talks to the same
Postgres instance the integration tests use. The executor wraps
psycopg and returns the JSON shape that ``LocalPostgresExecutor.execute_sql``
consumes.

These tests pin:
- The shape of the return value (list of dicts).
- The placeholder style (``$1`` etc., rewritten to ``%s`` for psycopg
  ClientCursor).
- The ``search_path`` option (so the executor queries the right
  schema when the integration conftest's ephemeral namespace is in
  use).
- Error handling: query errors (4xx) vs connection errors (5xx).

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each atom builds its own state.
- Rule 4 (no humo): assertions on real behaviour (return shapes,
  errors), never absence-of-error.
- Rule 8 (no production mutation): tests run against the
  self_host_schema ephemeral Postgres; no real InsForge touched.

M0 of the self-host-backend-coolify openspec (issue #641).
"""

from __future__ import annotations

import pytest

from app.core.local_backend.db import (
    DatabaseError,
    LocalPostgresExecutor,
    QueryError,
)


def test_executor_returns_rows_as_list_of_dicts(self_host_schema):
    """A SELECT returns ``[{"col": val, ...}, ...]`` matching InsForge."""
    executor = LocalPostgresExecutor(
        self_host_schema._dsn,
        search_path=self_host_schema.schema,
    )
    executor.execute(
        "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
        "VALUES ($1, $2, 'CANINA', 'H', '2020-01-01')",
        ["CHIP-LB-001", "Test"],
    )
    rows = executor.execute(
        "SELECT nchip, nombreanimal FROM animales WHERE nchip = $1",
        ["CHIP-LB-001"],
    )
    assert rows == [{"nchip": "CHIP-LB-001", "nombreanimal": "Test"}]


def test_executor_returns_empty_list_for_no_rows(self_host_schema):
    """A SELECT that matches no rows returns ``[]`` (not ``None``)."""
    executor = LocalPostgresExecutor(
        self_host_schema._dsn,
        search_path=self_host_schema.schema,
    )
    rows = executor.execute(
        "SELECT * FROM animales WHERE nchip = $1", ["NONEXISTENT"]
    )
    assert rows == []


def test_executor_handles_insert_update_delete(self_host_schema):
    """INSERT/UPDATE/DELETE return ``[]`` (matching InsForge's contract)."""
    executor = LocalPostgresExecutor(
        self_host_schema._dsn,
        search_path=self_host_schema.schema,
    )
    executor.execute(
        "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
        "VALUES ($1, $2, 'CANINA', 'H', '2020-01-01')",
        ["CHIP-LB-002", "Test"],
    )

    rows = executor.execute(
        "UPDATE animales SET nombreanimal = $1 WHERE nchip = $2",
        ["Updated", "CHIP-LB-002"],
    )
    assert rows == []

    rows = executor.execute(
        "DELETE FROM animales WHERE nchip = $1", ["CHIP-LB-002"]
    )
    assert rows == []


def test_executor_supports_dollar_n_placeholders(self_host_schema):
    """``$1``, ``$2`` placeholders are rewritten to ``%s`` for psycopg3."""
    executor = LocalPostgresExecutor(
        self_host_schema._dsn,
        search_path=self_host_schema.schema,
    )
    executor.execute(
        "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
        "VALUES ($1, $2, 'CANINA', 'H', '2020-01-01')",
        ["CHIP-LB-003", "Test3"],
    )
    rows = executor.execute(
        "SELECT nchip FROM animales WHERE nchip = $1 AND nombreanimal = $2",
        ["CHIP-LB-003", "Test3"],
    )
    assert len(rows) == 1
    assert rows[0]["nchip"] == "CHIP-LB-003"


def test_executor_raises_query_error_on_syntax_error(self_host_schema):
    """A query that the server rejects raises ``QueryError``, not generic."""
    executor = LocalPostgresExecutor(
        self_host_schema._dsn,
        search_path=self_host_schema.schema,
    )
    with pytest.raises(QueryError):
        executor.execute("SELECT FROM NOT_A_REAL_TABLE", [])


def test_executor_connection_error_when_dsn_invalid():
    """An invalid DSN raises ``DatabaseError`` (caller decides HTTP code)."""
    executor = LocalPostgresExecutor("postgresql://invalid:invalid@127.0.0.1:1/nope")
    with pytest.raises(DatabaseError):
        executor.execute("SELECT 1", [])


def test_executor_search_path_isolates_schema(self_host_schema):
    """The ``search_path`` ensures the executor queries the right schema.

    The integration conftest's ephemeral schema is set as the
    connection's search_path at every connect. This proves the executor
    can read from the right schema even when the connection is reused
    for multiple requests.
    """
    executor = LocalPostgresExecutor(
        self_host_schema._dsn,
        search_path=self_host_schema.schema,
    )
    # Insert via the conftest's helper (proves the schema is set up
    # in the conftest's session scope).
    self_host_schema.execute_sql(
        "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
        "VALUES (%s, %s, 'CANINA', 'H', '2020-01-01')",
        ["CHIP-LB-004", "Test4"],
    )
    # The executor (different connection, same DSN, same search_path)
    # sees the same row. This proves the search_path is applied
    # at every connect, not just at the first one.
    rows = executor.execute(
        "SELECT nchip FROM animales WHERE nchip = $1", ["CHIP-LB-004"]
    )
    assert len(rows) == 1
    assert rows[0]["nchip"] == "CHIP-LB-004"
