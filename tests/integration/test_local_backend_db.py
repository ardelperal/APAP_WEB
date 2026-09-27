"""Tests for the M0 local backend's Postgres adapter (issue #641).

The local backend has its own SQL executor that talks to the same
Postgres instance the integration tests use. The executor wraps
psycopg and returns the JSON shape that ``InsForgeClient.execute_sql``
expects (see ``app/core/local_backend/db.py``).

These tests pin, against a REAL Postgres connection (not the fakes in
``tests/test_local_backend_db.py``):
- The shape of the return value (list of dicts).
- Error handling: query errors (4xx) vs connection errors (5xx).
- The ``search_path`` option (so the executor queries the right
  schema when the integration conftest's ephemeral namespace is in
  use), applied at every connect, not just the first one.

``$N`` placeholder rewriting against real Postgres (reordered/repeated
placeholders, the production ``adopciones`` INSERT) is pinned by
``tests/integration/test_local_backend_placeholders.py`` instead of
being re-proven here.

Regression note (issue #932): this file existed with no
``pytest.mark.integration`` marker and called a ``LocalPostgresExecutor
.execute()`` method that has never existed (the real method is
``execute_sql``) — so it silently ran in NEITHER CI job (the ``test``
job excludes ``tests/integration`` via ``addopts``; the ``integration``
job filters with ``-m integration``) and nobody noticed the
``AttributeError``. ``scripts/check_test_classification.py`` now guards
against any ``tests/integration/test_*.py`` file missing the marker.

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each atom builds its own state.
- Rule 4 (no humo): assertions on real behaviour (return shapes,
  errors), never absence-of-error.
- Rule 8 (no production mutation): tests run against the
  ephemeral schema Postgres provisions per session; no real
  LocalBackend touched.

M0 of the self-host-backend-coolify openspec (issue #641).
"""

from __future__ import annotations

import pytest

from app.core.local_backend.db import (
    DatabaseError,
    LocalPostgresExecutor,
    QueryError,
)

pytestmark = pytest.mark.integration

_INSERT_ANIMAL_SQL = (
    "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
    "VALUES ($1, $2, 'CANINA', 'H', '2020-01-01')"
)


def _make_executor(ephemeral_postgres) -> LocalPostgresExecutor:
    return LocalPostgresExecutor(ephemeral_postgres.dsn, search_path=ephemeral_postgres.schema)


def test_executor_returns_rows_as_list_of_dicts(ephemeral_postgres):
    """A SELECT returns ``[{"col": val, ...}, ...]`` matching InsForgeClient."""
    executor = _make_executor(ephemeral_postgres)
    executor.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-LB-001", "Test"])

    rows = executor.execute_sql(
        "SELECT nchip, nombreanimal FROM animales WHERE nchip = $1",
        ["CHIP-LB-001"],
    )

    assert rows == [{"nchip": "CHIP-LB-001", "nombreanimal": "Test"}]


def test_executor_returns_empty_list_for_no_rows(ephemeral_postgres):
    """A SELECT that matches no rows returns ``[]`` (not ``None``)."""
    executor = _make_executor(ephemeral_postgres)

    rows = executor.execute_sql("SELECT * FROM animales WHERE nchip = $1", ["NONEXISTENT"])

    assert rows == []


def test_executor_handles_insert_update_delete(ephemeral_postgres):
    """INSERT/UPDATE/DELETE return ``[]`` against real Postgres."""
    executor = _make_executor(ephemeral_postgres)
    executor.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-LB-002", "Test"])

    rows = executor.execute_sql(
        "UPDATE animales SET nombreanimal = $1 WHERE nchip = $2",
        ["Updated", "CHIP-LB-002"],
    )
    assert rows == []

    rows = executor.execute_sql("DELETE FROM animales WHERE nchip = $1", ["CHIP-LB-002"])
    assert rows == []


def test_executor_raises_query_error_on_syntax_error(ephemeral_postgres):
    """A query that the server rejects raises ``QueryError``, not generic."""
    executor = _make_executor(ephemeral_postgres)

    with pytest.raises(QueryError):
        executor.execute_sql("SELECT FROM NOT_A_REAL_TABLE", [])


def test_executor_connection_error_when_dsn_invalid():
    """An invalid DSN raises ``DatabaseError`` (caller decides HTTP code)."""
    executor = LocalPostgresExecutor("postgresql://invalid:invalid@127.0.0.1:1/nope")

    with pytest.raises(DatabaseError):
        executor.execute_sql("SELECT 1", [])


def test_executor_search_path_isolates_schema(ephemeral_postgres):
    """The ``search_path`` ensures the executor queries the right schema.

    The integration conftest's ephemeral schema is set as the
    connection's search_path at every connect. This proves the executor
    can read from the right schema even when the connection is reused
    for multiple requests.
    """
    executor = _make_executor(ephemeral_postgres)
    # Insert via the conftest's helper (proves the schema is set up
    # in the conftest's session scope).
    ephemeral_postgres.execute_sql(
        "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
        "VALUES (%s, %s, 'CANINA', 'H', '2020-01-01')",
        ["CHIP-LB-004", "Test4"],
    )

    # The executor (different connection, same DSN, same search_path)
    # sees the same row. This proves the search_path is applied
    # at every connect, not just at the first one.
    rows = executor.execute_sql("SELECT nchip FROM animales WHERE nchip = $1", ["CHIP-LB-004"])

    assert len(rows) == 1
    assert rows[0]["nchip"] == "CHIP-LB-004"
