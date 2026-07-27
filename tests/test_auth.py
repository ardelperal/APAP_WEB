"""Tests for the usuarios_autorizados schema, bootstrap seed and CRUD.

All tests use a real ``InsForgeClient`` with an ``httpx.MockTransport``
so we exercise the SQL strings, params, and response parsing without
hitting the network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core import auth_cache
from app.core.auth import (
    Rol,
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


def test_ensure_schema_creates_usuarios_autorizados_table() -> None:
    """``ensure_schema_and_seed`` runs the CREATE TABLE IF NOT EXISTS statement."""
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _json_response(200, [])

    client = _client(handler)

    ensure_schema_and_seed(client, _settings())

    assert len(captured) == 1
    body = captured[0]
    assert "CREATE TABLE IF NOT EXISTS usuarios_autorizados" in body["query"]
    assert "email TEXT UNIQUE NOT NULL" in body["query"]
    assert "rol TEXT NOT NULL" in body["query"]
    assert "activo BOOLEAN" in body["query"]
    assert "fecha_alta TIMESTAMP" in body["query"]
    assert body["params"] == []


def test_ensure_schema_seeds_initial_admin_when_configured() -> None:
    """When ``initial_admin_email`` is set, the seed INSERT runs with that email."""
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        # The seed returns 1 row on first run.
        if "INSERT INTO usuarios_autorizados" in captured[-1]["query"]:
            return _json_response(200, [{"id": "u-1", "email": "owner@example.com", "rol": "developer"}])
        return _json_response(200, [])

    client = _client(handler)
    settings = _settings(initial_admin_email="owner@example.com")

    ensure_schema_and_seed(client, settings)

    # Two SQL calls: CREATE TABLE then INSERT.
    assert len(captured) == 2
    assert "CREATE TABLE IF NOT EXISTS usuarios_autorizados" in captured[0]["query"]
    insert = captured[1]
    assert "INSERT INTO usuarios_autorizados" in insert["query"]
    assert "SELECT $1, 'developer', true" in insert["query"]
    assert "WHERE NOT EXISTS" in insert["query"]
    assert "WHERE NOT EXISTS (\n    SELECT 1 FROM usuarios_autorizados WHERE rol = 'developer'" in insert["query"]
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
    assert "INSERT INTO usuarios_autorizados" not in captured[0]["query"]


def test_get_user_by_email_returns_row_when_active() -> None:
    """``get_user_by_email`` returns the row when the user exists and is active."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            [{"id": "u-1", "email": "a@b.com", "rol": "developer", "activo": True}],
        )

    client = _client(handler)

    user = get_user_by_email(client, "a@b.com")

    assert captured["body"]["params"] == ["a@b.com"]
    assert "WHERE email = $1" in captured["body"]["query"]
    assert "AND activo = true" in captured["body"]["query"]
    assert user == {
        "id": "u-1",
        "email": "a@b.com",
        "rol": "developer",
        "activo": True,
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
                    "rol": "key_user",
                    "activo": True,
                    "fecha_alta": "2026-06-17T00:00:00Z",
                },
                {
                    "id": "u-3",
                    "email": "c@c.com",
                    "rol": "reader",
                    "activo": False,
                    "fecha_alta": "2026-06-16T00:00:00Z",
                },
            ],
        )

    client = _client(handler)

    rows = list_authorized_users(client)

    assert "ORDER BY fecha_alta DESC" in captured["body"]["query"]
    assert len(rows) == 2
    assert rows[0]["email"] == "b@b.com"
    assert rows[1]["activo"] is False


def test_add_authorized_user_inserts_with_anadido_por() -> None:
    """``add_authorized_user`` runs an INSERT with email, rol and anadido_por."""
    captured: dict = {}
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        captured["body"] = json.loads(request.content)
        if "SELECT" in captured["body"]["query"]:
            # Pre-check: no existing user with this email
            return _json_response(200, [])
        call_count += 1
        # INSERT returns the new row
        return _json_response(
            200,
            [
                {
                    "id": "u-99",
                    "email": "new@example.com",
                    "rol": "key_user",
                    "activo": True,
                    "fecha_alta": "2026-06-17T00:00:00Z",
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
    assert "INSERT INTO usuarios_autorizados" in captured["body"]["query"]
    assert "VALUES ($1, $2, $3, true)" in captured["body"]["query"]
    assert "RETURNING id, email, rol, activo, fecha_alta" in captured["body"]["query"]
    assert row["id"] == "u-99"


def test_deactivate_authorized_user_returns_updated_row() -> None:
    """``deactivate_authorized_user`` returns the row with activo=False."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            [{"id": "u-1", "email": "a@b.com", "rol": "developer", "activo": False}],
        )

    client = _client(handler)

    row = deactivate_authorized_user(client, "u-1")

    assert captured["body"]["params"] == ["u-1"]
    assert "SET activo = false" in captured["body"]["query"]
    assert row is not None
    assert row["activo"] is False


def test_deactivate_authorized_user_returns_none_when_id_unknown() -> None:
    """``deactivate_authorized_user`` returns None when the id does not exist."""
    client = _client(lambda request: _json_response(200, []))

    assert deactivate_authorized_user(client, "u-unknown") is None


@pytest.mark.parametrize("role", [r.value for r in Rol])
def test_add_authorized_user_accepts_all_known_roles(role: str) -> None:
    """``add_authorized_user`` accepts every role in the ``Rol`` enum.

    Pins the contract that the role set accepted by the helper is
    derived from ``Rol`` (Rule 4 — one source of truth), so adding a
    new member to the enum automatically opens the door to that role
    without touching DDL. Regression guard for PR-2 (Slice 2): the DB
    ``CHECK`` constraint that used to duplicate the enum is gone, and
    the app is the sole validator.
    """
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        if "SELECT" in captured[-1]["query"]:
            # Pre-check: no existing user with this email
            return _json_response(200, [])
        # INSERT returns the new row
        return _json_response(
            200,
            [
                {
                    "id": f"u-{role}",
                    "email": f"{role}@example.com",
                    "rol": role,
                    "activo": True,
                    "fecha_alta": "2026-06-27T00:00:00Z",
                }
            ],
        )

    client = _client(handler)

    row = add_authorized_user(
        client,
        email=f"{role}@example.com",
        role=role,
        added_by="u-1",
    )

    assert len(captured) == 2, "pre-check SELECT and INSERT should both run"
    # captured[0] = pre-check SELECT (returns empty), captured[1] = INSERT
    assert captured[1]["params"][1] == role
    assert row["rol"] == role


# --- per-request auth cache invalidation (issue #143) ---------------------
#
# ``require_authorized_user`` caches authorization verdicts per email. When
# a user is added or deactivated the cached verdict is now stale, so the
# CRUD helpers MUST invalidate the affected email; otherwise a deactivate
# would not take effect until the TTL lapsed (the very bug #143 closes).


def test_add_authorized_user_invalidates_cache() -> None:
    """Adding a user drops any stale cached verdict for that email."""
    auth_cache.invalidate_all()
    auth_cache.set_cached_auth("new@example.com", is_authorized=False, rol=None)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "SELECT" in body["query"]:
            # Pre-check: no existing user
            return _json_response(200, [])
        # INSERT returns the new row
        return _json_response(
            200,
            [
                {
                    "id": "u-99",
                    "email": "new@example.com",
                    "rol": "key_user",
                    "activo": True,
                    "fecha_alta": "2026-06-17T00:00:00Z",
                }
            ],
        )

    add_authorized_user(
        _client(handler), email="new@example.com", role="key_user", added_by="u-1"
    )

    assert auth_cache.get_cached_auth("new@example.com", ttl_seconds=300) is None


def test_deactivate_authorized_user_invalidates_cache() -> None:
    """Deactivating a user drops the cached (stale, still-authorized) verdict.

    The email to invalidate is taken from the ``RETURNING`` row, so the
    helper does not need to be told the email separately.
    """
    auth_cache.invalidate_all()
    auth_cache.set_cached_auth("a@b.com", is_authorized=True, rol="developer")

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            200,
            [{"id": "u-1", "email": "a@b.com", "rol": "developer", "activo": False}],
        )

    deactivate_authorized_user(_client(handler), "u-1")

    assert auth_cache.get_cached_auth("a@b.com", ttl_seconds=300) is None


def test_deactivate_authorized_user_unknown_id_does_not_touch_cache() -> None:
    """A no-op deactivate (unknown id) must not raise trying to read a row."""
    auth_cache.invalidate_all()
    client = _client(lambda request: _json_response(200, []))

    assert deactivate_authorized_user(client, "u-unknown") is None


# --- Issue #277 / #278: canonical email identity -------------------------------


def test_add_authorized_user_rejects_empty_email() -> None:
    """add_authorized_user("") raises ValueError("email cannot be empty")."""
    client = _client(lambda request: _json_response(200, []))
    with pytest.raises(ValueError, match="email cannot be empty"):
        add_authorized_user(client, email="", role="key_user", added_by="u-1")


def test_add_authorized_user_rejects_malformed_email() -> None:
    """add_authorized_user("notanemail") raises ValueError about format."""
    client = _client(lambda request: _json_response(200, []))
    with pytest.raises(ValueError, match="email format invalid"):
        add_authorized_user(client, email="notanemail", role="key_user", added_by="u-1")


def test_add_authorized_user_rejects_duplicate_normalized_email_precheck() -> None:
    """When the pre-insert SELECT finds the canonical email, raise ValueError."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        # The SELECT for get_user_by_email returns a row (duplicate detected)
        if "SELECT" in captured["body"]["query"]:
            return _json_response(
                200,
                [{"id": "u-1", "email": "maria@lopez.com", "rol": "key_user", "activo": True}],
            )
        return _json_response(200, [])

    client = _client(handler)
    with pytest.raises(ValueError, match="email already authorized"):
        add_authorized_user(client, email=" Maria@Lopez.com ", role="key_user", added_by="u-1")

    # The duplicate check used the canonical form in SQL
    assert "maria@lopez.com" in captured["body"]["params"]


def test_add_authorized_user_rejects_duplicate_via_insforge_error() -> None:
    """When the pre-check passes but INSERT raises InsForgeError(23505), raise ValueError."""
    from app.core.insforge import InsForgeError

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        body = json.loads(request.content)
        if "SELECT" in body["query"]:
            # Pre-check: no existing user
            return _json_response(200, [])
        call_count += 1
        if call_count == 1:
            # INSERT: InsForge unique violation
            raise InsForgeError(
                409,
                {"code": "23505", "message": "duplicate key value violates unique constraint"},
            )
        return _json_response(200, [])

    client = _client(handler)
    with pytest.raises(ValueError, match="email already authorized"):
        add_authorized_user(client, email="new@example.com", role="key_user", added_by="u-1")


def test_get_user_by_email_normalizes_case_before_sql() -> None:
    """get_user_by_email normalizes its argument before the SQL lookup."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _json_response(
            200,
            [{"id": "u-1", "email": "maria@lopez.com", "rol": "key_user", "activo": True}],
        )

    client = _client(handler)
    user = get_user_by_email(client, " Maria@Lopez.com ")

    assert captured["body"]["params"] == ["maria@lopez.com"]
    assert user is not None
