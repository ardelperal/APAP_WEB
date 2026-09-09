"""Tests for the usuarios_autorizados schema, bootstrap seed and CRUD.

All tests use a ``_FakeSqlExecutor`` implementing the
:class:`~app.core.data_access.SqlExecutor` Protocol directly so we
exercise the SQL strings, params, and response parsing without hitting
the network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
from app.core.data_access import DuplicateKeyError


class _FakeSqlExecutor:
    """Minimal ``SqlExecutor`` Protocol implementation for unit tests.

    Supports two response strategies:

    * ``set_response`` / ``set_responses`` — queue rows consumed in order
      (used by tests that want straight-line behaviour).
    * ``set_handler`` — a per-call callable that inspects the SQL +
      params and returns rows OR raises a Protocol-level exception
      (used by tests that need to simulate a 4xx/5xx error response,
      e.g. the 23505 unique-key violation).

    Returns ``[]`` when neither strategy matches so the fake never
    accidentally short-circuits a "row missing" branch.
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
        self, handler: Callable[[str, list[object]], Any],
    ) -> None:
        self._handler = handler

    def execute_sql(
        self, query: str, params: list[object] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        if self._handler is not None:
            return self._handler(query, list(params or []))
        if self._responses:
            return self._responses.pop(0)
        return []


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
    fake = _FakeSqlExecutor()
    fake.set_response([])

    ensure_schema_and_seed(fake, _settings())

    assert len(fake.calls) == 1
    query = fake.calls[0][0]
    assert "CREATE TABLE IF NOT EXISTS usuarios_autorizados" in query
    assert "email TEXT UNIQUE NOT NULL" in query
    assert "rol TEXT NOT NULL" in query
    assert "activo BOOLEAN" in query
    assert "fecha_alta TIMESTAMP" in query
    assert fake.calls[0][1] == []


def test_ensure_schema_seeds_initial_admin_when_configured() -> None:
    """When ``initial_admin_email`` is set, the seed INSERT runs with that email."""
    fake = _FakeSqlExecutor()
    fake.set_responses(
        [],  # CREATE TABLE → no rows
        [{"id": "u-1", "email": "owner@example.com", "rol": "developer"}],  # INSERT → row
    )
    settings = _settings(initial_admin_email="owner@example.com")

    ensure_schema_and_seed(fake, settings)

    # Two SQL calls: CREATE TABLE then INSERT.
    assert len(fake.calls) == 2
    assert "CREATE TABLE IF NOT EXISTS usuarios_autorizados" in fake.calls[0][0]
    insert = fake.calls[1]
    assert "INSERT INTO usuarios_autorizados" in insert[0]
    assert "SELECT $1, 'developer', true" in insert[0]
    assert "WHERE NOT EXISTS" in insert[0]
    assert "WHERE NOT EXISTS (\n    SELECT 1 FROM usuarios_autorizados WHERE rol = 'developer'" in insert[0]
    assert insert[1] == ["owner@example.com"]


def test_ensure_schema_skips_seed_when_no_initial_email() -> None:
    """When ``initial_admin_email`` is empty, no INSERT runs (only the CREATE)."""
    fake = _FakeSqlExecutor()
    fake.set_response([])
    settings = _settings(initial_admin_email="")

    ensure_schema_and_seed(fake, settings)

    assert len(fake.calls) == 1
    assert "INSERT INTO usuarios_autorizados" not in fake.calls[0][0]


def test_get_user_by_email_returns_row_when_active() -> None:
    """``get_user_by_email`` returns the row when the user exists and is active."""
    fake = _FakeSqlExecutor()
    fake.set_response(
        [{"id": "u-1", "email": "a@b.com", "rol": "developer", "activo": True}],
    )

    user = get_user_by_email(fake, "a@b.com")

    query, params = fake.calls[0]
    assert params == ["a@b.com"]
    assert "WHERE email = $1" in query
    assert "AND activo = true" in query
    assert user == {
        "id": "u-1",
        "email": "a@b.com",
        "rol": "developer",
        "activo": True,
    }


def test_get_user_by_email_returns_none_when_not_found() -> None:
    """``get_user_by_email`` returns None when the response is empty."""
    fake = _FakeSqlExecutor()
    fake.set_response([])

    assert get_user_by_email(fake, "ghost@example.com") is None


def test_list_authorized_users_returns_all_rows() -> None:
    """``list_authorized_users`` returns every user (active + inactive) for the admin panel."""
    fake = _FakeSqlExecutor()
    fake.set_response(
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

    rows = list_authorized_users(fake)

    assert "ORDER BY fecha_alta DESC" in fake.calls[0][0]
    assert len(rows) == 2
    assert rows[0]["email"] == "b@b.com"
    assert rows[1]["activo"] is False


def test_add_authorized_user_inserts_with_anadido_por() -> None:
    """``add_authorized_user`` runs an INSERT with email, rol and anadido_por."""
    fake = _FakeSqlExecutor()
    fake.set_responses(
        [],  # pre-check SELECT: no existing user
        [   # INSERT: new row
            {
                "id": "u-99",
                "email": "new@example.com",
                "rol": "key_user",
                "activo": True,
                "fecha_alta": "2026-06-17T00:00:00Z",
            }
        ],
    )

    row = add_authorized_user(
        fake,
        email="new@example.com",
        role="key_user",
        added_by="u-1",
    )

    insert_call = fake.calls[1]
    assert insert_call[1] == ["new@example.com", "key_user", "u-1"]
    assert "INSERT INTO usuarios_autorizados" in insert_call[0]
    assert "VALUES ($1, $2, $3, true)" in insert_call[0]
    assert "RETURNING id, email, rol, activo, fecha_alta" in insert_call[0]
    assert row["id"] == "u-99"


def test_deactivate_authorized_user_returns_updated_row() -> None:
    """``deactivate_authorized_user`` returns the row with activo=False."""
    fake = _FakeSqlExecutor()
    fake.set_response(
        [{"id": "u-1", "email": "a@b.com", "rol": "developer", "activo": False}],
    )

    row = deactivate_authorized_user(fake, "u-1")

    assert fake.calls[0][1] == ["u-1"]
    assert "SET activo = false" in fake.calls[0][0]
    assert row is not None
    assert row["activo"] is False


def test_deactivate_authorized_user_raises_when_user_not_found() -> None:
    """``deactivate_authorized_user`` raises ValueError when the id does not exist.

    Issue #279: the function disambiguates 'not found' from 'last developer'
    via get_user_by_id. When the user does not exist, ValueError is raised
    so the route can display a meaningful flash rather than silently redirect.
    """
    fake = _FakeSqlExecutor()

    def handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "SET activo = false" in query:
            return []
        if (
            "SELECT id, email, rol, activo FROM usuarios_autorizados WHERE id ="
            in query
        ):
            return []  # user not found
        return []

    fake.set_handler(handler)

    with pytest.raises(ValueError, match="user not found"):
        deactivate_authorized_user(fake, "u-unknown")


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
    fake = _FakeSqlExecutor()
    fake.set_responses(
        [],  # pre-check SELECT: no existing user
        [   # INSERT: new row
            {
                "id": f"u-{role}",
                "email": f"{role}@example.com",
                "rol": role,
                "activo": True,
                "fecha_alta": "2026-06-27T00:00:00Z",
            }
        ],
    )

    row = add_authorized_user(
        fake,
        email=f"{role}@example.com",
        role=role,
        added_by="u-1",
    )

    assert len(fake.calls) == 2, "pre-check SELECT and INSERT should both run"
    # fake.calls[0] = pre-check SELECT (returns empty), fake.calls[1] = INSERT
    assert fake.calls[1][1][1] == role
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

    fake = _FakeSqlExecutor()
    fake.set_responses(
        [],  # pre-check SELECT: no existing user
        [   # INSERT: new row
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
        fake, email="new@example.com", role="key_user", added_by="u-1",
    )

    assert auth_cache.get_cached_auth("new@example.com", ttl_seconds=300) is None


def test_deactivate_authorized_user_invalidates_cache() -> None:
    """Deactivating a user drops the cached (stale, still-authorized) verdict.

    The email to invalidate is taken from the ``RETURNING`` row, so the
    helper does not need to be told the email separately.
    """
    auth_cache.invalidate_all()
    auth_cache.set_cached_auth("a@b.com", is_authorized=True, rol="developer")

    fake = _FakeSqlExecutor()
    fake.set_response(
        [{"id": "u-1", "email": "a@b.com", "rol": "developer", "activo": False}],
    )

    deactivate_authorized_user(fake, "u-1")

    assert auth_cache.get_cached_auth("a@b.com", ttl_seconds=300) is None


def test_deactivate_authorized_user_unknown_id_does_not_touch_cache() -> None:
    """Deactivating an unknown user raises ValueError and does not touch the cache.

    The disambiguation SELECT finds no user, so ValueError is raised before
    any cache invalidation occurs.
    """
    auth_cache.invalidate_all()
    auth_cache.set_cached_auth("any@example.com", is_authorized=True, rol="developer")

    fake = _FakeSqlExecutor()

    def handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "SET activo = false" in query:
            return []
        if (
            "SELECT id, email, rol, activo FROM usuarios_autorizados WHERE id ="
            in query
        ):
            return []  # user not found
        return []

    fake.set_handler(handler)

    with pytest.raises(ValueError, match="user not found"):
        deactivate_authorized_user(fake, "u-unknown")

    # Cache was NOT invalidated because the error raised before that step
    assert auth_cache.get_cached_auth("any@example.com", ttl_seconds=300) is not None


# --- Issue #277 / #278: canonical email identity -------------------------------


def test_add_authorized_user_rejects_empty_email() -> None:
    """add_authorized_user("") raises ValueError("email cannot be empty")."""
    fake = _FakeSqlExecutor()
    fake.set_response([])
    with pytest.raises(ValueError, match="email cannot be empty"):
        add_authorized_user(fake, email="", role="key_user", added_by="u-1")


def test_add_authorized_user_rejects_malformed_email() -> None:
    """add_authorized_user("notanemail") raises ValueError about format."""
    fake = _FakeSqlExecutor()
    fake.set_response([])
    with pytest.raises(ValueError, match="email format invalid"):
        add_authorized_user(fake, email="notanemail", role="key_user", added_by="u-1")


def test_add_authorized_user_rejects_duplicate_normalized_email_precheck() -> None:
    """When the pre-insert SELECT finds the canonical email, raise ValueError."""
    fake = _FakeSqlExecutor()
    fake.set_response(
        [{"id": "u-1", "email": "maria@lopez.com", "rol": "key_user", "activo": True}],
    )
    with pytest.raises(ValueError, match="email already authorized"):
        add_authorized_user(fake, email=" Maria@Lopez.com ", role="key_user", added_by="u-1")

    # The duplicate check used the canonical form in SQL
    assert "maria@lopez.com" in fake.calls[0][1]


def test_add_authorized_user_rejects_duplicate_via_insforge_error() -> None:
    """When the pre-check passes but INSERT 23505s, raise ValueError.

    The handler raises :class:`~app.core.data_access.DuplicateKeyError`
    the way the real backend does for a Postgres ``23505`` SQLSTATE, and
    ``add_authorized_user`` translates it to ``ValueError`` at the
    application boundary (issue #277 fix).
    """
    fake = _FakeSqlExecutor()

    def handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "SELECT" in query:
            return []  # pre-check: no existing user
        # INSERT raises the Protocol-level DuplicateKeyError — the
        # backend translation of a 23505 unique-violation.
        raise DuplicateKeyError("duplicate key value violates unique constraint")

    fake.set_handler(handler)

    with pytest.raises(ValueError, match="email already authorized"):
        add_authorized_user(fake, email="new@example.com", role="key_user", added_by="u-1")
    # The service caught the Protocol-level exception, not the transport
    # envelope — guards against a regression where the catch reverts to
    # ``except InsForgeError``.
    assert issubclass(DuplicateKeyError, Exception)


def test_get_user_by_email_normalizes_case_before_sql() -> None:
    """get_user_by_email normalizes its argument before the SQL lookup."""
    fake = _FakeSqlExecutor()
    fake.set_response(
        [{"id": "u-1", "email": "maria@lopez.com", "rol": "key_user", "activo": True}],
    )

    user = get_user_by_email(fake, " Maria@Lopez.com ")

    assert fake.calls[0][1] == ["maria@lopez.com"]
    assert user is not None


# --- Issue #279: last-active-developer guard -------------------------------


def test_deactivate_authorized_user_raises_when_last_developer() -> None:
    """Deactivating the only active developer raises ValueError.

    REQ-1 scenario: Last developer deactivation raises.
    The conditional UPDATE returns zero rows; _has_other_active_developers
    confirms no other active developer exists → ValueError.
    """
    fake = _FakeSqlExecutor()

    def handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "SET activo = false" in query:
            return []  # conditional UPDATE: zero rows (this IS the last developer)
        if "SELECT EXISTS" in query:
            return [{"exists": False}]  # no other developer
        if (
            "SELECT id, email, rol, activo" in query
            and "WHERE id =" in query
        ):
            # get_user_by_id disambiguation
            return [
                {
                    "id": "dev-only",
                    "email": "dev@example.com",
                    "rol": "developer",
                    "activo": True,
                }
            ]
        return []

    fake.set_handler(handler)

    with pytest.raises(ValueError, match="cannot deactivate the last active developer"):
        deactivate_authorized_user(fake, "dev-only")


def test_deactivate_authorized_user_succeeds_when_other_developer_exists() -> None:
    """Deactivating one of two developers succeeds without ValueError.

    REQ-1 scenario: Non-last developer deactivation succeeds.
    REQ-3: Self-deactivation permitted when others exist.
    """
    fake = _FakeSqlExecutor()
    fake.set_response(
        [
            {
                "id": "dev1",
                "email": "dev1@example.com",
                "rol": "developer",
                "activo": False,
            }
        ],
    )

    row = deactivate_authorized_user(fake, "dev1")
    assert row is not None
    assert row["activo"] is False
    assert row["id"] == "dev1"


def test_deactivate_reader_does_not_fire_developer_guard() -> None:
    """Deactivating a reader bypasses the last-developer guard.

    REQ-2: Guard fires only for developer role.
    The conditional UPDATE succeeds because rol <> 'developer' condition is met.
    """
    fake = _FakeSqlExecutor()
    fake.set_response(
        [
            {
                "id": "reader1",
                "email": "reader@example.com",
                "rol": "reader",
                "activo": False,
            }
        ],
    )

    row = deactivate_authorized_user(fake, "reader1")
    assert row is not None
    assert row["rol"] == "reader"
    assert row["activo"] is False


def test_deactivate_admin_does_not_fire_developer_guard() -> None:
    """Deactivating an admin (non-developer) bypasses the last-developer guard.

    REQ-2: Guard fires only for developer role.
    """
    fake = _FakeSqlExecutor()
    fake.set_response(
        [
            {
                "id": "admin1",
                "email": "admin@example.com",
                "rol": "admin",
                "activo": False,
            }
        ],
    )

    row = deactivate_authorized_user(fake, "admin1")
    assert row is not None
    assert row["rol"] == "admin"
    assert row["activo"] is False


def test_deactivate_key_user_does_not_fire_developer_guard() -> None:
    """Deactivating a key_user (non-developer) bypasses the last-developer guard.

    REQ-2: Guard fires only for developer role.
    """
    fake = _FakeSqlExecutor()
    fake.set_response(
        [
            {
                "id": "key1",
                "email": "key@example.com",
                "rol": "key_user",
                "activo": False,
            }
        ],
    )

    row = deactivate_authorized_user(fake, "key1")
    assert row is not None
    assert row["rol"] == "key_user"
    assert row["activo"] is False


def test_deactivate_unknown_user_raises_value_error() -> None:
    """Deactivating a non-existent user raises ValueError.

    The conditional UPDATE affects zero rows; get_user_by_id confirms the user
    does not exist, so ValueError is raised. The route renders a flash error.
    """
    fake = _FakeSqlExecutor()

    def handler(query: str, params: list[object]) -> list[dict[str, object]]:
        if "SET activo = false" in query:
            return []
        if (
            "SELECT id, email, rol, activo FROM usuarios_autorizados WHERE id ="
            in query
        ):
            return []  # user not found
        return []

    fake.set_handler(handler)

    with pytest.raises(ValueError, match="user not found"):
        deactivate_authorized_user(fake, "ghost-id")


# --- Issue #279: SEED filter on activo = true ------------------------------


def test_ensure_schema_seeds_when_no_active_developer_exists() -> None:
    """Seed INSERT fires when only inactive developer rows exist.

    REQ-5 scenario: Seed inserts when no active developer exists.
    The WHERE NOT EXISTS subquery now checks rol='developer' AND activo=true,
    so an inactive developer row does NOT suppress the seed.
    """
    fake = _FakeSqlExecutor()
    fake.set_responses(
        [],  # CREATE TABLE
        [   # INSERT: fires because no ACTIVE developer exists
            {"id": "seed-1", "email": "owner@example.com", "rol": "developer"}
        ],
    )
    settings = _settings(initial_admin_email="owner@example.com")

    ensure_schema_and_seed(fake, settings)

    assert len(fake.calls) == 2
    insert = fake.calls[1]
    assert "INSERT INTO usuarios_autorizados" in insert[0]
    assert "SELECT $1, 'developer', true" in insert[0]
    # The key assertion: activo = true filter in the subquery
    assert "activo = true" in insert[0]
