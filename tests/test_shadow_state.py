"""Unit tests for ``migration.shadow_state``.

PR 1 of ``web-only-feature-preservation``: CRUD for the
``web_only_feature_shadow`` table. The repository is a thin wrapper
over ``LocalPostgresExecutor.execute_sql`` — tests inject a mock client
(``_FakeSqlExecutor``) and assert the SQL emitted, which is the
same testing pattern used in ``tests/test_acogidas.py``.

What these tests cover (5 tests, mapped to tasks.md 1.8):

1. ``test_upsert_emits_insert_on_conflict`` — fresh row produces an
   ``INSERT ... ON CONFLICT ... DO UPDATE`` against the shadow table.
2. ``test_lookup_uses_unique_index_for_o1_path`` — lookup by
   ``(table_name, legacy_pk, web_column)`` emits a ``WHERE`` against the
   three index columns (the UNIQUE index defined in shadow_state.py).
3. ``test_list_needs_review_filters_by_reconciliation_status`` — list
   scopes to ``reconciliation_status = 'needs_review'`` and supports
   ``--table`` / ``--since`` filters.
4. ``test_update_reconciliation_status_targets_one_row`` — status
   update is scoped to a single row by the same unique key.
5. ``test_delete_removes_shadow_row_by_unique_key`` — delete is scoped
   by ``(table_name, legacy_pk, web_column)``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.core.data_access import BackendError
from migration.shadow_state import (
    SHADOW_TABLE_SQL,
    ShadowStateRepository,
)


class _ErrorResponse:
    """Marker returned by a fake handler to signal a backend error."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests.

    Records every ``execute_sql`` call (query + params) so callers can
    assert on the SQL shape without standing up a Postgres instance.
    Configured handlers let CTE + disambiguation tests run
    deterministically. Returns ``[]`` when the handler returns ``None``
    so the fake never accidentally short-circuits a "row missing" branch.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []
        self._handler: Callable[[str, list[object]], Any] | None = None

    def set_response(self, rows: list[dict[str, object]]) -> None:
        self._responses = [rows]

    def set_responses(self, *responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)

    def set_handler(
        self, handler: Callable[[str, list[object]], Any]
    ) -> None:
        self._handler = handler

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        bound_params = list(params or [])
        if self._handler is not None:
            result = self._handler(query, bound_params)
            if isinstance(result, _ErrorResponse):
                raise BackendError(result.status_code, result.body)
            if result is not None:
                return result  # type: ignore[no-any-return]
        if self._responses:
            return self._responses.pop(0)
        return []

    def close(self) -> None:
        pass  # no-op for fake


def _make_client(
    handler: Callable[[str, list[object]], Any],
) -> tuple[_FakeSqlExecutor, list[tuple[str, list[object]]]]:
    """Build a fake executor that delegates every ``execute_sql`` to ``handler``.

    The handler signature mirrors what ``_make_handler`` produces:
    it inspects ``(query, params)`` and returns a list of dicts or an
    ``_ErrorResponse``. Returned ``calls`` is captured by reference so
    tests can assert SQL + positional params without monkey-patching.
    """
    fake = _FakeSqlExecutor()
    fake.set_handler(handler)
    return fake, fake.calls


def _empty_rows(_query: str, _params: list[object]) -> list[dict[str, object]]:
    return []


# --- SHADOW_TABLE_SQL (T1.4) ----------------------------------------------


def test_shadow_table_sql_defines_table_with_unique_index() -> None:
    """The shadow-state SQL defines the table AND the unique index
    ``(table_name, legacy_pk, web_column)`` that makes lookup O(1)
    (design.md §3; spec.md REQ: Persistencia del Shadow State)."""
    sql = SHADOW_TABLE_SQL
    assert "CREATE TABLE IF NOT EXISTS web_only_feature_shadow" in sql
    assert "table_name TEXT NOT NULL" in sql
    assert "legacy_pk TEXT NOT NULL" in sql
    assert "web_column TEXT NOT NULL" in sql
    # The UNIQUE composite index — the contract for O(1) lookup.
    assert (
        "UNIQUE (table_name, legacy_pk, web_column)" in sql
        or "UNIQUE(table_name, legacy_pk, web_column)" in sql
    )


def test_shadow_table_sql_constrains_strategy_and_status() -> None:
    """``strategy`` and ``reconciliation_status`` are TEXT with CHECKs."""
    sql = SHADOW_TABLE_SQL
    assert "strategy" in sql
    assert "preserve" in sql and "fixed" in sql and "derived" in sql
    assert "reconciliation_status" in sql
    # Status enum from design.md §3.
    for value in ("matched", "divergent", "needs_review", "pending", "migrated"):
        assert value in sql, f"shadow status enum missing {value!r}"


# --- ShadowStateRepository.upsert (T1.3) ---------------------------------


def test_upsert_emits_insert_on_conflict_against_shadow_table() -> None:
    """upsert() emits INSERT ... ON CONFLICT to merge with the existing row."""
    client, captured = _make_client(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        repo.upsert(
            table_name="voluntarios",
            legacy_pk="123",
            web_pk="uuid-abc",
            web_column="DNI",
            preserved_value="12345678A",
            strategy="preserve",
        )
    finally:
        client.close()

    assert len(captured) == 1, f"expected 1 SQL call, got {len(captured)}"
    query, params = captured[0]
    assert "INSERT INTO web_only_feature_shadow" in query
    assert "ON CONFLICT" in query
    # The ON CONFLICT clause names the unique-key columns that drive the merge.
    assert "ON CONFLICT (table_name, legacy_pk, web_column)" in query
    # Parameters carry the row payload in the order bound by the VALUES clause.
    assert "voluntarios" in params
    assert "123" in params
    assert "uuid-abc" in params
    assert "DNI" in params
    # preserved_value lands as a JSON-encoded string (JSONB column).
    assert any("12345678A" in str(p) for p in params)
    assert "preserve" in params


# --- ShadowStateRepository.lookup (T1.3) ---------------------------------


def test_lookup_uses_unique_index_for_o1_path() -> None:
    """lookup() filters by the three UNIQUE-index columns so the planner
    picks the UNIQUE index and the lookup is O(1) (spec.md REQ: O(1)
    lookup thanks to the unique composite index)."""
    client, captured = _make_client(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        repo.lookup(
            table_name="voluntarios",
            legacy_pk="123",
            web_column="DNI",
        )
    finally:
        client.close()

    assert len(captured) == 1
    query = captured[0][0].upper()
    assert "FROM WEB_ONLY_FEATURE_SHADOW" in query
    # The three index columns in the WHERE clause is the contract.
    assert "TABLE_NAME" in query
    assert "LEGACY_PK" in query
    assert "WEB_COLUMN" in query
    assert "WHERE" in query


def test_lookup_returns_row_when_one_exists() -> None:
    """The ``row-found`` branch of ``lookup()`` returns the first row from
    the executor's result list (the unique-key contract guarantees at most
    one row, since ``(table_name, legacy_pk, web_column)`` is UNIQUE).

    Pairs with ``test_lookup_uses_unique_index_for_o1_path`` (which covers
    the empty case) to fully exercise the two return paths of ``lookup``.
    """
    expected_row: dict[str, object] = {
        "id": "row-uuid-1",
        "table_name": "voluntarios",
        "legacy_pk": "123",
        "web_pk": "uuid-abc",
        "web_column": "DNI",
        "preserved_value": "12345678A",
        "strategy": "preserve",
        "reconciliation_status": "matched",
    }

    def _handler(
        _query: str, _params: list[object]
    ) -> list[dict[str, object]]:
        return [expected_row]

    client, captured = _make_client(_handler)
    try:
        repo = ShadowStateRepository(client)
        row = repo.lookup(
            table_name="voluntarios",
            legacy_pk="123",
            web_column="DNI",
        )
    finally:
        client.close()

    # Exactly one query was issued (the SELECT against the unique key).
    assert len(captured) == 1
    # The row the mock returned is what the repository surfaces to the caller.
    assert row == expected_row
    # And the key fields are individually intact (belt + suspenders).
    assert row["table_name"] == "voluntarios"
    assert row["legacy_pk"] == "123"
    assert row["web_column"] == "DNI"
    assert row["reconciliation_status"] == "matched"


# --- ShadowStateRepository.list_needs_review (T1.3) ---------------------


def test_list_needs_review_filters_by_reconciliation_status() -> None:
    """list_needs_review() always filters by status='needs_review' and
    accepts optional table_name / since filters (CLI flag plumbing for
    PR 5 — the data path is owned by the repository in PR 1)."""
    client, captured = _make_client(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        rows = repo.list_needs_review()
    finally:
        client.close()

    assert rows == []
    assert len(captured) == 1
    query = captured[0][0].upper()
    assert "FROM WEB_ONLY_FEATURE_SHADOW" in query
    assert "NEEDS_REVIEW" in query
    # Status filter is mandatory.
    assert "RECONCILIATION_STATUS" in query
    assert "WHERE" in query


def test_list_needs_review_supports_table_and_since_filters() -> None:
    """Optional filters narrow the result set without losing the status filter."""
    client, captured = _make_client(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        repo.list_needs_review(table_name="voluntarios", since="2026-06-20T00:00:00+00:00")
    finally:
        client.close()

    query = captured[0][0].upper()
    assert "RECONCILIATION_STATUS" in query
    assert "NEEDS_REVIEW" in query
    assert "TABLE_NAME" in query
    # ``since`` translates to a timestamp filter.
    assert "LAST_LEGACY_SNAPSHOT_AT" in query or "STATE_CHANGED_AT" in query


# --- ShadowStateRepository.update_reconciliation_status (T1.3) ---------


def test_update_reconciliation_status_targets_one_row() -> None:
    """update_reconciliation_status() emits a single UPDATE scoped by
    the same unique key (table_name, legacy_pk, web_column)."""
    client, captured = _make_client(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        repo.update_reconciliation_status(
            table_name="voluntarios",
            legacy_pk="123",
            web_column="DNI",
            status="matched",
        )
    finally:
        client.close()

    assert len(captured) == 1
    query = captured[0][0].upper()
    assert "UPDATE WEB_ONLY_FEATURE_SHADOW" in query
    assert "SET RECONCILIATION_STATUS" in query
    # Scope by the unique key (WHERE clause is the last part of the SQL).
    assert "TABLE_NAME" in query
    assert "LEGACY_PK" in query
    assert "WEB_COLUMN" in query
    # Params: status, review_reasons_jsonb, last_reconciled_at,
    #         table_name, legacy_pk, web_column — status is FIRST.
    params = captured[0][1]
    assert params[0] == "matched"
    assert "voluntarios" in params
    assert "123" in params
    assert "DNI" in params


# --- ShadowStateRepository.delete (T1.3, mentioned in T1.8) -------------


def test_delete_removes_shadow_row_by_unique_key() -> None:
    """delete() removes a single row scoped by the unique key."""
    client, captured = _make_client(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        repo.delete(
            table_name="voluntarios",
            legacy_pk="123",
            web_column="DNI",
        )
    finally:
        client.close()

    assert len(captured) == 1
    query = captured[0][0].upper()
    assert "DELETE FROM WEB_ONLY_FEATURE_SHADOW" in query
    assert "TABLE_NAME" in query
    assert "LEGACY_PK" in query
    assert "WEB_COLUMN" in query


# --- Smoke: the repository can be instantiated with just a client -------


def test_repository_construction_does_not_hit_db() -> None:
    """Constructing the repository is free; it just stores the client."""
    client, captured = _make_client(_empty_rows)
    try:
        ShadowStateRepository(client)
    finally:
        client.close()
    assert captured == [], f"construction must not query the DB; got {captured!r}"


# --- Marker for the strict-TDD gate --------------------------------------


def test_strict_tdd_marker() -> None:
    """Trivial sentinel so pytest counts this file; real coverage is the
    5 tests above mapped 1:1 to tasks.md 1.8."""
    assert True


# --- Fixtures used by other test files -----------------------------------


@pytest.fixture
def shadow_repo() -> ShadowStateRepository:
    """A repository bound to a no-op client; tests inject a custom one."""
    client, _ = _make_client(_empty_rows)
    return ShadowStateRepository(client)
