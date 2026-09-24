"""Unit tests for ``app.core.local_backend.db`` (issue #913, A-01 CRAP gate).

The CI ``test`` job's coverage run excludes ``tests/integration`` (see
``.github/workflows/ci.yml``), so ``tests/integration/test_local_backend_db.py``
and ``tests/integration/test_local_backend_transaction.py`` — which exercise
this module against a real Postgres — never contribute to the per-commit
``coverage.json`` that ``scripts/check_crap.py`` reads. These tests pin the
same behaviour with hand-written fake ``psycopg`` connection/cursor objects
(no Postgres), injected via ``monkeypatch`` on
``LocalPostgresExecutor._connect``, so the module-level helpers and both
executors are covered where the CRAP gate actually measures them.

Characterization note: every helper/method covered here already existed
before this PR (``_to_client_placeholders``, ``_translate_psycopg_error``,
``execute_sql``, ``transaction``) or is a pure extraction that preserves
behaviour (``_fetch_rows``/``_rows_as_dicts`` split out of ``_run_on_cursor``
in this same PR, see ``app/core/local_backend/db.py``). These tests were
run and passed BEFORE and AFTER that extraction, confirming it changed
structure, not behaviour.

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each fake builds its own isolated state per test.
- Rule 4 (no humo): assertions pin real return values, exception types, and
  call sequences (commit/rollback/close), never absence-of-error.
- Rule 8 (no production mutation): no real connection is ever opened.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from app.core.data_access import NestedTransactionError
from app.core.local_backend.db import (
    DatabaseError,
    LocalPostgresExecutor,
    QueryError,
    _BoundTransactionExecutor,
    _fetch_rows,
    _rows_as_dicts,
    _run_on_cursor,
    _to_client_placeholders,
    _translate_psycopg_error,
)


class FakeCursor:
    """Minimal ``psycopg.Cursor``-shaped double: records calls, no I/O."""

    def __init__(
        self,
        *,
        rows: list[Any] | None = None,
        description: list[tuple[str, ...]] | None = None,
        execute_error: Exception | None = None,
        fetch_error: Exception | None = None,
    ) -> None:
        self.rows = [] if rows is None else rows
        self.description = description or []
        self._execute_error = execute_error
        self._fetch_error = fetch_error
        self.executed: list[tuple[str, Any]] = []
        self.closed = False

    def execute(self, query: str, params: Any) -> None:
        self.executed.append((query, params))
        if self._execute_error is not None:
            raise self._execute_error

    def fetchall(self) -> list[Any]:
        if self._fetch_error is not None:
            raise self._fetch_error
        return self.rows

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    """Minimal ``psycopg.Connection``-shaped double.

    Unlike the real ``psycopg.Connection.__exit__`` (which also commits or
    rolls back), this fake's ``__exit__`` only closes: ``execute_sql`` and
    ``transaction()`` already call ``commit()``/``rollback()`` explicitly,
    so these tests pin THAT explicit call sequence rather than re-deriving
    psycopg's own context-manager semantics (already pinned by
    ``tests/integration/test_local_backend_transaction.py`` against real
    Postgres).
    """

    def __init__(
        self,
        cursor: FakeCursor | None = None,
        *,
        commit_error: Exception | None = None,
    ) -> None:
        self._cursor = cursor or FakeCursor()
        self._commit_error = commit_error
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self.close()
        return False


# ── _to_client_placeholders ──────────────────────────────────────────────


def test_to_client_placeholders_leaves_query_without_dollar_unchanged() -> None:
    query = "SELECT * FROM animales"
    assert _to_client_placeholders(query, None) == (query, [])


def test_to_client_placeholders_rewrites_sequential_placeholders() -> None:
    query = "INSERT INTO animales (nchip, nombreanimal) VALUES ($1, $2)"
    assert _to_client_placeholders(query, ["CHIP-1", "Rex"]) == (
        "INSERT INTO animales (nchip, nombreanimal) VALUES (%s, %s)",
        ["CHIP-1", "Rex"],
    )


def test_to_client_placeholders_reorders_params_to_occurrence_order() -> None:
    query = "UPDATE animales SET nombreanimal = $2 WHERE id = $1"
    assert _to_client_placeholders(query, ["id-1", "Rex"]) == (
        "UPDATE animales SET nombreanimal = %s WHERE id = %s",
        ["Rex", "id-1"],
    )


def test_to_client_placeholders_repeats_params_for_repeated_placeholders() -> None:
    query = "SELECT * FROM animales WHERE nchip = $1 OR nombreanimal = $1"
    assert _to_client_placeholders(query, ["X"]) == (
        "SELECT * FROM animales WHERE nchip = %s OR nombreanimal = %s",
        ["X", "X"],
    )


def test_to_client_placeholders_escapes_literal_percent() -> None:
    query = "SELECT * FROM animales WHERE nombreanimal LIKE 'R%' AND nchip = $1"
    assert _to_client_placeholders(query, ["C"]) == (
        "SELECT * FROM animales WHERE nombreanimal LIKE 'R%%' AND nchip = %s",
        ["C"],
    )


def test_to_client_placeholders_rejects_placeholder_without_param() -> None:
    with pytest.raises(QueryError, match=r"\$2"):
        _to_client_placeholders("SELECT $1, $2", ["only-one"])


# ── _translate_psycopg_error ─────────────────────────────────────────────


def test_translate_psycopg_error_with_sqlstate_returns_query_error() -> None:
    exc = psycopg.errors.UniqueViolation("duplicate key")
    assert isinstance(exc.sqlstate, str)  # characterize: UniqueViolation carries one

    translated = _translate_psycopg_error(exc)

    assert isinstance(translated, QueryError)
    assert not isinstance(translated, DatabaseError)


def test_translate_psycopg_error_without_sqlstate_returns_database_error() -> None:
    exc = psycopg.OperationalError("connection refused")
    assert exc.sqlstate is None  # characterize: OperationalError carries none

    translated = _translate_psycopg_error(exc)

    assert isinstance(translated, DatabaseError)
    assert not isinstance(translated, QueryError)


# ── _fetch_rows ───────────────────────────────────────────────────────────


def test_fetch_rows_returns_fetched_rows() -> None:
    cur = FakeCursor(rows=[(1, "a"), (2, "b")])
    assert _fetch_rows(cur) == [(1, "a"), (2, "b")]


def test_fetch_rows_returns_empty_list_on_programming_error() -> None:
    cur = FakeCursor(fetch_error=psycopg.ProgrammingError("no results to fetch"))
    assert _fetch_rows(cur) == []


# ── _rows_as_dicts ────────────────────────────────────────────────────────


def test_rows_as_dicts_returns_empty_list_unchanged() -> None:
    assert _rows_as_dicts([], [("nchip",)]) == []


def test_rows_as_dicts_passes_through_rows_already_dicts() -> None:
    rows = [{"nchip": "CHIP-1"}]
    assert _rows_as_dicts(rows, [("nchip",)]) is rows


def test_rows_as_dicts_converts_tuples_using_description() -> None:
    rows = [(1, "Rex"), (2, "Fido")]
    description = [("id",), ("nombreanimal",)]

    result = _rows_as_dicts(rows, description)

    assert result == [{"id": 1, "nombreanimal": "Rex"}, {"id": 2, "nombreanimal": "Fido"}]


# ── _run_on_cursor ────────────────────────────────────────────────────────


def test_run_on_cursor_returns_rows_as_dicts() -> None:
    cur = FakeCursor(rows=[(1, "Rex")], description=[("id",), ("nombreanimal",)])

    result = _run_on_cursor(cur, "SELECT id, nombreanimal FROM animales", None)

    assert result == [{"id": 1, "nombreanimal": "Rex"}]


def test_run_on_cursor_rewrites_dollar_placeholders_before_execute() -> None:
    cur = FakeCursor()

    _run_on_cursor(cur, "SELECT * FROM animales WHERE nchip = $1", ["CHIP-1"])

    assert cur.executed == [("SELECT * FROM animales WHERE nchip = %s", ["CHIP-1"])]


def test_run_on_cursor_defaults_none_params_to_empty_list() -> None:
    cur = FakeCursor()

    _run_on_cursor(cur, "DELETE FROM animales", None)

    assert cur.executed == [("DELETE FROM animales", [])]


def test_run_on_cursor_returns_empty_list_for_insert_style_statement() -> None:
    cur = FakeCursor(fetch_error=psycopg.ProgrammingError("no results to fetch"))

    assert _run_on_cursor(cur, "INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"]) == []


def test_run_on_cursor_raises_query_error_for_sqlstate_execute_failure() -> None:
    cur = FakeCursor(execute_error=psycopg.errors.UniqueViolation("duplicate key"))

    with pytest.raises(QueryError):
        _run_on_cursor(cur, "INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])


def test_run_on_cursor_raises_database_error_for_connection_execute_failure() -> None:
    cur = FakeCursor(execute_error=psycopg.OperationalError("connection refused"))

    with pytest.raises(DatabaseError):
        _run_on_cursor(cur, "SELECT 1", None)


# ── LocalPostgresExecutor.execute_sql ──────────────────────────────────────


def test_execute_sql_commits_and_closes_cursor_and_connection_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rows=[(1, "Rex")], description=[("id",), ("nombreanimal",)])
    conn = FakeConnection(cur)
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    result = executor.execute_sql("SELECT id, nombreanimal FROM animales")

    assert result == [{"id": 1, "nombreanimal": "Rex"}]
    assert conn.committed is True
    assert conn.rolled_back is False
    assert cur.closed is True
    assert conn.closed is True


def test_execute_sql_rolls_back_and_reraises_query_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(execute_error=psycopg.errors.UniqueViolation("duplicate key"))
    conn = FakeConnection(cur)
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    with pytest.raises(QueryError):
        executor.execute_sql("INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])

    assert conn.committed is False
    assert conn.rolled_back is True
    assert cur.closed is True
    assert conn.closed is True


def test_execute_sql_translates_and_rolls_back_on_commit_failure_with_sqlstate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rows=[])
    conn = FakeConnection(cur, commit_error=psycopg.errors.UniqueViolation("deferred fk"))
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    with pytest.raises(QueryError):
        executor.execute_sql("INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])

    assert conn.rolled_back is True
    assert cur.closed is True
    assert conn.closed is True


def test_execute_sql_translates_commit_failure_without_sqlstate_as_database_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rows=[])
    conn = FakeConnection(cur, commit_error=psycopg.OperationalError("connection lost"))
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    with pytest.raises(DatabaseError):
        executor.execute_sql("INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])

    assert conn.rolled_back is True
    assert cur.closed is True


# ── LocalPostgresExecutor.transaction ──────────────────────────────────────


def test_transaction_commits_and_closes_connection_on_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rows=[])
    conn = FakeConnection(cur)
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    with executor.transaction() as txn:
        txn.execute_sql("INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])

    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True


def test_transaction_rolls_back_and_recloses_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(FakeCursor())
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    with pytest.raises(RuntimeError, match="forced failure"):
        with executor.transaction() as txn:
            txn.execute_sql("INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])
            raise RuntimeError("forced failure")

    assert conn.committed is False
    assert conn.rolled_back is True
    assert conn.closed is True


def test_transaction_translates_commit_failure_and_still_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(FakeCursor(), commit_error=psycopg.errors.UniqueViolation("deferred fk"))
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    with pytest.raises(QueryError):
        with executor.transaction() as txn:
            txn.execute_sql("INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])

    assert conn.committed is False
    assert conn.closed is True


def test_transaction_yields_bound_executor_whose_transaction_call_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(FakeCursor())
    executor = LocalPostgresExecutor("postgresql://unused")
    monkeypatch.setattr(executor, "_connect", lambda: conn)

    with pytest.raises(NestedTransactionError):
        with executor.transaction() as txn:
            txn.transaction()


# ── _BoundTransactionExecutor ───────────────────────────────────────────────


def test_bound_transaction_executor_runs_on_shared_connection_without_committing() -> None:
    cur = FakeCursor(rows=[(1, "Rex")], description=[("id",), ("nombreanimal",)])
    conn = FakeConnection(cur)
    bound = _BoundTransactionExecutor(conn)

    result = bound.execute_sql("SELECT id, nombreanimal FROM animales")

    assert result == [{"id": 1, "nombreanimal": "Rex"}]
    assert conn.committed is False
    assert conn.rolled_back is False
    assert cur.closed is True


def test_bound_transaction_executor_closes_cursor_even_on_query_error() -> None:
    cur = FakeCursor(execute_error=psycopg.errors.UniqueViolation("duplicate key"))
    conn = FakeConnection(cur)
    bound = _BoundTransactionExecutor(conn)

    with pytest.raises(QueryError):
        bound.execute_sql("INSERT INTO animales (nchip) VALUES ($1)", ["CHIP-1"])

    assert cur.closed is True
    assert conn.committed is False


def test_bound_transaction_executor_transaction_raises_without_calling_connect() -> None:
    conn = FakeConnection(FakeCursor())
    bound = _BoundTransactionExecutor(conn)

    with pytest.raises(NestedTransactionError, match="nested transaction"):
        bound.transaction()
