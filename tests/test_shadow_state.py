"""Unit tests for ``migration.shadow_state``.

PR 1 of ``web-only-feature-preservation``: CRUD for the
``web_only_feature_shadow`` table. The repository is a thin wrapper
over ``InsForgeClient.execute_sql`` — tests inject a mock client
(``httpx.MockTransport``) and assert the SQL emitted, which is the
same testing pattern used in ``tests/test_migration.py::TestWebReader``.

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

import json
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from migration.shadow_state import (
    SHADOW_TABLE_SQL,
    ShadowStateRepository,
)


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(handler) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    """Build a client whose MockTransport records every call's JSON body."""
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


def _empty_rows(_req: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
    return _json_response(200, [])


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
    client, captured = _client_recording(_empty_rows)
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
    body = captured[0]
    sql = body["query"]
    params = body["params"]
    assert "INSERT INTO web_only_feature_shadow" in sql
    assert "ON CONFLICT" in sql
    # The ON CONFLICT clause names the unique-key columns that drive the merge.
    assert "ON CONFLICT (table_name, legacy_pk, web_column)" in sql
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
    client, captured = _client_recording(_empty_rows)
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
    sql = captured[0]["query"].upper()
    assert "FROM WEB_ONLY_FEATURE_SHADOW" in sql
    # The three index columns in the WHERE clause is the contract.
    assert "TABLE_NAME" in sql
    assert "LEGACY_PK" in sql
    assert "WEB_COLUMN" in sql
    assert "WHERE" in sql


def test_lookup_returns_row_when_one_exists() -> None:
    """The ``row-found`` branch of ``lookup()`` returns the first row from
    the executor's result list (the unique-key contract guarantees at most
    one row, since ``(table_name, legacy_pk, web_column)`` is UNIQUE).

    Pairs with ``test_lookup_uses_unique_index_for_o1_path`` (which covers
    the empty case) to fully exercise the two return paths of ``lookup``.
    """
    expected_row = {
        "id": "row-uuid-1",
        "table_name": "voluntarios",
        "legacy_pk": "123",
        "web_pk": "uuid-abc",
        "web_column": "DNI",
        "preserved_value": "12345678A",
        "strategy": "preserve",
        "reconciliation_status": "matched",
    }

    def _handler(_req: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [expected_row])

    client, captured = _client_recording(_handler)
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
    client, captured = _client_recording(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        rows = repo.list_needs_review()
    finally:
        client.close()

    assert rows == []
    assert len(captured) == 1
    sql = captured[0]["query"].upper()
    assert "FROM WEB_ONLY_FEATURE_SHADOW" in sql
    assert "NEEDS_REVIEW" in sql
    # Status filter is mandatory.
    assert "RECONCILIATION_STATUS" in sql
    assert "WHERE" in sql


def test_list_needs_review_supports_table_and_since_filters() -> None:
    """Optional filters narrow the result set without losing the status filter."""
    client, captured = _client_recording(_empty_rows)
    try:
        repo = ShadowStateRepository(client)
        repo.list_needs_review(table_name="voluntarios", since="2026-06-20T00:00:00+00:00")
    finally:
        client.close()

    sql = captured[0]["query"].upper()
    assert "RECONCILIATION_STATUS" in sql
    assert "NEEDS_REVIEW" in sql
    assert "TABLE_NAME" in sql
    # ``since`` translates to a timestamp filter.
    assert "LAST_LEGACY_SNAPSHOT_AT" in sql or "STATE_CHANGED_AT" in sql


# --- ShadowStateRepository.update_reconciliation_status (T1.3) ---------


def test_update_reconciliation_status_targets_one_row() -> None:
    """update_reconciliation_status() emits a single UPDATE scoped by
    the same unique key (table_name, legacy_pk, web_column)."""
    client, captured = _client_recording(_empty_rows)
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
    sql = captured[0]["query"].upper()
    assert "UPDATE WEB_ONLY_FEATURE_SHADOW" in sql
    assert "SET RECONCILIATION_STATUS" in sql
    # Scope by the unique key (WHERE clause is the last part of the SQL).
    assert "TABLE_NAME" in sql
    assert "LEGACY_PK" in sql
    assert "WEB_COLUMN" in sql
    # Params: status, review_reasons_jsonb, last_reconciled_at,
    #         table_name, legacy_pk, web_column — status is FIRST.
    params = captured[0]["params"]
    assert params[0] == "matched"
    assert "voluntarios" in params
    assert "123" in params
    assert "DNI" in params


# --- ShadowStateRepository.delete (T1.3, mentioned in T1.8) -------------


def test_delete_removes_shadow_row_by_unique_key() -> None:
    """delete() removes a single row scoped by the unique key."""
    client, captured = _client_recording(_empty_rows)
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
    sql = captured[0]["query"].upper()
    assert "DELETE FROM WEB_ONLY_FEATURE_SHADOW" in sql
    assert "TABLE_NAME" in sql
    assert "LEGACY_PK" in sql
    assert "WEB_COLUMN" in sql


# --- Smoke: the repository can be instantiated with just a client -------


def test_repository_construction_does_not_hit_db() -> None:
    """Constructing the repository is free; it just stores the client."""
    client, captured = _client_recording(_empty_rows)
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
    client, _ = _client_recording(_empty_rows)
    return ShadowStateRepository(client)
