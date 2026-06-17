"""Tests for the authorized_users schema, bootstrap seed and CRUD.

All tests use a real ``InsForgeClient`` with an ``httpx.MockTransport``
so we exercise the SQL strings, params, and response parsing without
hitting the network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.auth import (
    add_authorized_user,
    deactivate_authorized_user,
    ensure_schema_and_seed,
    get_user_by_email,
    list_authorized_users,
)
from app.core.config import Settings
from app.core.insforge import InsForgeClient


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client(handler) -> InsForgeClient:
    return InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )


def _settings(**overrides) -> Settings:
    base = dict(
        app_name="APAP_WEB",
        version="0.1.0",
        insforge_url="https://example.insforge.app",
        insforge_anon_key="",
        insforge_service_key="ik_test",
        google_client_id="",
        google_client_secret="",
        google_redirect_uri="http://127.0.0.1:8000/auth/callback",
        initial_admin_email="",
        session_secret="test-secret",
        debug=False,
    )
    base.update(overrides)
    return Settings(**base)


def test_ensure_schema_creates_authorized_users_table() -> None:
    """``ensure_schema_and_seed`` runs the CREATE TABLE IF NOT EXISTS statement."""
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _json_response(200, [])

    client = _client(handler)

    ensure_schema_and_seed(client, _settings())

    assert len(captured) == 1
    body = captured[0]
    assert "CREATE TABLE IF NOT EXISTS authorized_users" in body["query"]
    assert "email TEXT UNIQUE NOT NULL" in body["query"]
    assert "role TEXT NOT NULL" in body["query"]
    assert "is_active BOOLEAN" in body["query"]
    assert body["params"] == []


def test_ensure_schema_seeds_initial_admin_when_configured() -> None:
    """When ``initial_admin_email`` is set, the seed INSERT runs with that email."""
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        # The seed returns 1 row on first run.
        if "INSERT INTO authorized_users" in captured[-1]["query"]:
            return _json_response(200, [{"id": "u-1", "email": "owner@example.com"}])
        return _json_response(200, [])

    client = _client(handler)
    settings = _settings(initial_admin_email="owner@example.com")

    ensure_schema_and_seed(client, settings)

    # Two SQL calls: CREATE TABLE then INSERT.
    assert len(captured) == 2
    assert "CREATE TABLE IF NOT EXISTS authorized_users" in captured[0]["query"]
    insert = captured[1]
    assert "INSERT INTO authorized_users" in insert["query"]
    assert "SELECT $1, 'developer', true" in insert["query"]
    assert "WHERE NOT EXISTS" in insert["query"]
    assert insert["params"] == ["owner@example.com"]


def test_ensure_schema_skips_seed_when_no_initial_email() -> None:
    """When ``initial_admin_email`` is empty, no INSERT runs (only the CREATE)."""
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _json_response(200, [])

    client = _client(handler)
    settings = _settings(initial_admin_email="")

    ensure_schema_and_seed(client, settings)

    assert len(captured) == 1
    assert "INSERT INTO authorized_users" not in captured[0]["query"]


def test_get_user_by_email_returns_row_when_active() -> None:
    """``get_user_by_email`` returns the row when the user exists and is active."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            [{"id": "u-1", "email": "a@b.com", "role": "developer", "is_active": True}],
        )

    client = _client(handler)

    user = get_user_by_email(client, "a@b.com")

    assert captured["body"]["params"] == ["a@b.com"]
    assert "WHERE email = $1" in captured["body"]["query"]
    assert "AND is_active = true" in captured["body"]["query"]
    assert user == {
        "id": "u-1",
        "email": "a@b.com",
        "role": "developer",
        "is_active": True,
    }


def test_get_user_by_email_returns_none_when_not_found() -> None:
    """``get_user_by_email`` returns None when the response is empty."""
    client = _client(lambda request: _json_response(200, []))

    assert get_user_by_email(client, "ghost@example.com") is None


def test_list_authorized_users_returns_all_rows() -> None:
    """``list_authorized_users`` returns every user (active + inactive) for the admin panel."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            [
                {
                    "id": "u-2",
                    "email": "b@b.com",
                    "role": "key_user",
                    "is_active": True,
                    "created_at": "2026-06-17T00:00:00Z",
                },
                {
                    "id": "u-3",
                    "email": "c@c.com",
                    "role": "reader",
                    "is_active": False,
                    "created_at": "2026-06-16T00:00:00Z",
                },
            ],
        )

    client = _client(handler)

    rows = list_authorized_users(client)

    assert "ORDER BY created_at DESC" in captured["body"]["query"]
    assert len(rows) == 2
    assert rows[0]["email"] == "b@b.com"
    assert rows[1]["is_active"] is False


def test_add_authorized_user_inserts_with_added_by() -> None:
    """``add_authorized_user`` runs an INSERT with email, role and added_by."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            [
                {
                    "id": "u-99",
                    "email": "new@example.com",
                    "role": "key_user",
                    "is_active": True,
                    "created_at": "2026-06-17T00:00:00Z",
                }
            ],
        )

    client = _client(handler)

    row = add_authorized_user(
        client,
        email="new@example.com",
        role="key_user",
        added_by="u-1",
    )

    assert captured["body"]["params"] == ["new@example.com", "key_user", "u-1"]
    assert "INSERT INTO authorized_users" in captured["body"]["query"]
    assert "VALUES ($1, $2, $3, true)" in captured["body"]["query"]
    assert "RETURNING id, email, role, is_active, created_at" in captured["body"]["query"]
    assert row["id"] == "u-99"


def test_deactivate_authorized_user_returns_updated_row() -> None:
    """``deactivate_authorized_user`` returns the row with is_active=False."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            [{"id": "u-1", "email": "a@b.com", "role": "developer", "is_active": False}],
        )

    client = _client(handler)

    row = deactivate_authorized_user(client, "u-1")

    assert captured["body"]["params"] == ["u-1"]
    assert "SET is_active = false" in captured["body"]["query"]
    assert row is not None
    assert row["is_active"] is False


def test_deactivate_authorized_user_returns_none_when_id_unknown() -> None:
    """``deactivate_authorized_user`` returns None when the id does not exist."""
    client = _client(lambda request: _json_response(200, []))

    assert deactivate_authorized_user(client, "u-unknown") is None
