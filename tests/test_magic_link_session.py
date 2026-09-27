"""Unit tests for the magic-link session helpers (issue #917).

Covers the helpers introduced to close finding A-05 (epic #911):

- ``_resolve_auth_users_port`` — the AuthUsersPort resolution order
  (test override → ``sql_executor`` → ``local_postgres_executor`` →
  ``None``).
- ``_lookup_authorized_user`` — fail-closed semantics: ``None`` when
  no port is wired, when the email is unknown, and on transport
  errors.
- ``_build_session_payload`` — the payload must match the OAuth
  callback contract exactly (``csrf_token``, ``user_id``, ``rol``,
  ``email``, ``is_authorized``).
- ``_unauthorized_redirect`` — generic 302, no session cookie.

The route-level behaviour (real app, real Postgres, full CSRF
middleware) is covered by ``tests/integration/test_magic_link_real_app.py``.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from app.core.data_access import BackendError
from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser
from app.core.local_backend.db import DatabaseError, QueryError
from app.core.local_backend.magic_link import (
    _build_session_payload,
    _lookup_authorized_user,
    _resolve_auth_users_port,
    _unauthorized_redirect,
)

# --- fakes --------------------------------------------------------------------


class _FakeAuthPort:
    """Minimal AuthUsersPort stand-in: only ``get_user_by_email`` is used."""

    def __init__(
        self,
        user: AuthorizedUser | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._user = user
        self._exc = exc
        self.calls: list[str] = []

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        self.calls.append(email)
        if self._exc is not None:
            raise self._exc
        return self._user


class _FakeExecutor:
    """Opaque executor sentinel — the resolver never calls it directly."""

    def __init__(self, name: str) -> None:
        self.name = name


def _user() -> AuthorizedUser:
    return AuthorizedUser(
        id="u-917",
        email="magic@test.com",
        rol=Rol.KEY_USER,
        active=True,
    )


# --- _resolve_auth_users_port ---------------------------------------------------


def test_resolve_prefers_test_override_over_executors() -> None:
    """``app.state._auth_users_port`` wins over any wired executor."""
    app = FastAPI()
    override = _FakeAuthPort()
    app.state._auth_users_port = override
    app.state.sql_executor = _FakeExecutor("sql")
    app.state.local_postgres_executor = _FakeExecutor("local")

    assert _resolve_auth_users_port(app) is override


def test_resolve_uses_sql_executor_production_path() -> None:
    """No override + ``sql_executor`` wired → adapter over that executor."""
    from app.core.local_backend.auth_adapter import LocalBackendAuthUsersAdapter

    app = FastAPI()
    executor = _FakeExecutor("sql")
    app.state.sql_executor = executor

    port = _resolve_auth_users_port(app)
    assert isinstance(port, LocalBackendAuthUsersAdapter)
    assert port._executor is executor


def test_resolve_falls_back_to_local_postgres_executor() -> None:
    """Standalone local-backend app exposes the executor under the M0 name."""
    from app.core.local_backend.auth_adapter import LocalBackendAuthUsersAdapter

    app = FastAPI()
    executor = _FakeExecutor("local")
    app.state.local_postgres_executor = executor

    port = _resolve_auth_users_port(app)
    assert isinstance(port, LocalBackendAuthUsersAdapter)
    assert port._executor is executor


def test_resolve_returns_none_without_any_executor() -> None:
    """No override and no executor → ``None`` (caller must fail closed)."""
    app = FastAPI()
    assert _resolve_auth_users_port(app) is None


# --- _lookup_authorized_user ----------------------------------------------------


def test_lookup_returns_user_via_port() -> None:
    app = FastAPI()
    user = _user()
    port = _FakeAuthPort(user=user)
    app.state._auth_users_port = port

    assert _lookup_authorized_user(app, "magic@test.com") is user
    assert port.calls == ["magic@test.com"]


def test_lookup_returns_none_when_no_port_wired() -> None:
    """No port resolvable → fail closed with ``None``."""
    app = FastAPI()
    assert _lookup_authorized_user(app, "magic@test.com") is None


@pytest.mark.parametrize(
    "exc",
    [
        BackendError(503, b"backend down"),
        DatabaseError("db down"),
        QueryError("bad query"),
    ],
    ids=["backend", "database", "query"],
)
def test_lookup_fails_closed_on_transport_errors(exc: Exception) -> None:
    """Transport errors must NOT mint a session: ``None``, never raise."""
    app = FastAPI()
    app.state._auth_users_port = _FakeAuthPort(exc=exc)

    assert _lookup_authorized_user(app, "magic@test.com") is None


def test_lookup_returns_none_for_unknown_email() -> None:
    """Adapter/port returning ``None`` (inactive or unknown email) → ``None``."""
    app = FastAPI()
    app.state._auth_users_port = _FakeAuthPort(user=None)

    assert _lookup_authorized_user(app, "ghost@test.com") is None


# --- _build_session_payload -----------------------------------------------------


def test_session_payload_matches_oauth_contract() -> None:
    """The payload keys MUST equal the OAuth callback session contract
    (app/core/auth_flow.py: ``issue_csrf_to_session`` over ``{email,
    user_id, rol, is_authorized}``)."""
    payload = _build_session_payload(_user())

    assert set(payload.keys()) == {
        "email",
        "user_id",
        "rol",
        "is_authorized",
        "csrf_token",
    }
    assert payload["email"] == "magic@test.com"
    assert payload["user_id"] == "u-917"
    assert payload["rol"] == "key_user"
    assert payload["is_authorized"] is True
    assert isinstance(payload["csrf_token"], str) and payload["csrf_token"]


def test_session_payload_issues_fresh_token_per_call() -> None:
    """Two payloads never share a CSRF token (fresh entropy per mint)."""
    first = _build_session_payload(_user())
    second = _build_session_payload(_user())

    assert first["csrf_token"] != second["csrf_token"]


# --- _unauthorized_redirect -----------------------------------------------------


def test_unauthorized_redirect_is_generic_302_without_cookie() -> None:
    """Generic fail-closed redirect: 302 to /unauthorized, no Set-Cookie."""
    response = _unauthorized_redirect()

    assert response.status_code == 302
    assert response.headers["location"] == "/unauthorized"
    assert "set-cookie" not in response.headers


def test_unauthorized_redirect_has_empty_body() -> None:
    """No oracle content in the body (generic redirect, no error detail)."""
    response: Any = _unauthorized_redirect()
    assert response.body == b""
