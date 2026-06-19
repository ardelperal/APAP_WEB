"""Tests for the domain schema bootstrap (animals, volunteers, volunteer_roles).

Mirrors the pattern in ``tests/test_auth.py``: real ``InsForgeClient`` with
``httpx.MockTransport`` so we exercise the SQL strings, params, and
response parsing without hitting the network. The schema definitions are
verified structurally (columns, types, constraints, FKs) by parsing the
SQL strings, which keeps the test honest about what the code intends to
create.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from app.core.domain import (
    ANIMALS_CREATE_TABLE_SQL,
    VOLUNTEERS_CREATE_TABLE_SQL,
    VOLUNTEER_ROLES_CREATE_TABLE_SQL,
    ensure_domain_schema,
)
from app.core.insforge import InsForgeClient


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
        return _json_response(200, [])

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


def _column_names(sql: str) -> set[str]:
    """Return the set of column names declared in a CREATE TABLE statement.

    Naive parser: finds the parenthesised body of ``CREATE TABLE [IF NOT
    EXISTS] <name> ( ... )`` and splits on commas at depth 0. Good enough
    for the column names we want to assert; foreign-key targets live in a
    separate ``REFERENCES`` clause and are tested directly.
    """
    match = re.search(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+\w+\s*\((.*)\)\s*$", sql, re.DOTALL)
    assert match is not None, f"could not parse CREATE TABLE body from: {sql!r}"
    body = match.group(1)
    columns: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            columns.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        columns.append("".join(current).strip())
    names: set[str] = set()
    for col in columns:
        first = col.split()[0] if col.split() else ""
        # Skip constraint lines (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK)
        if first.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            continue
        names.add(first)
    return names


def _fk_targets(sql: str) -> list[tuple[str, str]]:
    """Return the list of (column, referenced_table) pairs declared via REFERENCES.

    Tolerates column-level constraints between the type and the
    ``REFERENCES`` keyword (e.g. ``UUID NOT NULL REFERENCES foo(id)``).
    """
    pairs: list[tuple[str, str]] = []
    for m in re.finditer(
        r"(\w+)\s+UUID(?:\s+NOT\s+NULL)?\s+REFERENCES\s+(\w+)\s*\(\s*id\s*\)",
        sql,
    ):
        pairs.append((m.group(1), m.group(2)))
    return pairs


# --- animals --------------------------------------------------------------


def test_animals_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS animals" in ANIMALS_CREATE_TABLE_SQL


def test_animals_create_table_sql_has_required_columns() -> None:
    columns = _column_names(ANIMALS_CREATE_TABLE_SQL)
    required = {
        "id",
        "chip_number",
        "name",
        "species",
        "sex",
        "birth_date",
        "breed",
        "is_mestizo",
        "is_ppp",
        "photo_url",
        "death_date",
        "death_cause",
        "ariac_notified",
        "last_state_before_death",
        "created_at",
        "updated_at",
    }
    missing = required - columns
    assert not missing, f"animals table missing required columns: {sorted(missing)}"


def test_animals_table_enforces_species_and_sex_domains() -> None:
    sql = ANIMALS_CREATE_TABLE_SQL
    assert "species IN ('CANINA', 'FELINA')" in sql
    assert "sex IN ('M', 'H')" in sql


def test_animals_chip_number_is_unique() -> None:
    assert "chip_number TEXT UNIQUE NOT NULL" in ANIMALS_CREATE_TABLE_SQL


# --- volunteers -----------------------------------------------------------


def test_volunteers_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS volunteers" in VOLUNTEERS_CREATE_TABLE_SQL


def test_volunteers_create_table_sql_has_required_columns() -> None:
    columns = _column_names(VOLUNTEERS_CREATE_TABLE_SQL)
    required = {"id", "full_name", "email", "phone", "dni", "is_active", "created_at", "updated_at"}
    missing = required - columns
    assert not missing, f"volunteers table missing required columns: {sorted(missing)}"


def test_volunteers_email_is_unique() -> None:
    assert "email TEXT UNIQUE" in VOLUNTEERS_CREATE_TABLE_SQL


# --- volunteer_roles ------------------------------------------------------


def test_volunteer_roles_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS volunteer_roles" in VOLUNTEER_ROLES_CREATE_TABLE_SQL


def test_volunteer_roles_references_volunteers() -> None:
    pairs = _fk_targets(VOLUNTEER_ROLES_CREATE_TABLE_SQL)
    assert ("volunteer_id", "volunteers") in pairs


def test_volunteer_roles_enforces_role_type_domain() -> None:
    sql = VOLUNTEER_ROLES_CREATE_TABLE_SQL
    assert "role_type IN ('intake', 'follow_up', 'foster_care', 'health')" in sql


def test_volunteer_roles_has_unique_volunteer_role_pair() -> None:
    assert "UNIQUE (volunteer_id, role_type)" in VOLUNTEER_ROLES_CREATE_TABLE_SQL


# --- ensure_domain_schema orchestration -----------------------------------


def test_ensure_domain_schema_creates_all_three_tables() -> None:
    client, captured = _client_recording(lambda req: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    assert len(captured) == 3
    queries = [c["query"].strip() for c in captured]
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS animals") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS volunteers") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS volunteer_roles") for q in queries)


def test_ensure_domain_schema_order_is_animals_then_volunteers_then_roles() -> None:
    """Roles references volunteers, volunteers is independent, animals is independent.

    Order: animals, volunteers, volunteer_roles. Anything else means a
    foreign-key will fail on a clean database.
    """
    client, captured = _client_recording(lambda req: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    assert queries[0].startswith("CREATE TABLE IF NOT EXISTS animals")
    assert queries[1].startswith("CREATE TABLE IF NOT EXISTS volunteers")
    assert queries[2].startswith("CREATE TABLE IF NOT EXISTS volunteer_roles")


def test_ensure_domain_schema_raises_when_create_table_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(500, {"error": "boom"})

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(Exception):  # noqa: PT011 — InsForgeError, asserted by side effect
        ensure_domain_schema(client)
    client.close()
