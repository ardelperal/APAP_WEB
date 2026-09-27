"""Route-level tests for voluntarios role management (epic #420 VOL-02).

Tests the add/remove role POST endpoints:
- POST /voluntarios/{id}/roles/add — assigns role.
- POST /voluntarios/{id}/roles/remove — removes role.
- RBAC: reader rol receives 403 on both write endpoints (issue #144).

The reader-403 tests below (issue #1041, mirroring the closed PR #1033
/ commit 4a9401b precedent) install a per-test SQL executor that echoes
the cookie's ``rol`` on the auth revalidation SELECT. The conftest
default spy hardcodes ``rol=key_user`` for every reval, masking
reader-403 regressions — exactly the rot this slice closes. The autouse
``_clear_settings_cache`` fixture in ``tests/conftest.py`` also calls
``auth_cache.invalidate_all()`` so a prior test cannot prime the verdict
for the same email under the wrong rol.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.di.local_postgres_di import get_local_postgres_executor_dep
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app
from app.modules.voluntarios.di import get_voluntarios_port
from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort
from tests.conftest import auth_reval_rows, make_csrf_request


class _VoluntariosPortSpy:
    __slots__ = (
        "captured_calls", "get_row", "assign_unique_violation",
        "assign_error", "remove_error",
    )

    def __init__(self) -> None:
        self.captured_calls: list[tuple[str, ...]] = []
        self.get_row: Voluntario | None = Voluntario(
            id="v-1", voluntario="Ana Garcia", activo=True
        )
        self.assign_unique_violation = False
        self.assign_error: Exception | None = None
        self.remove_error: Exception | None = None

    def get_voluntario_by_id(self, voluntario_id: str) -> Voluntario | None:
        self.captured_calls.append(("get_voluntario_by_id", voluntario_id))
        return self.get_row

    def list_voluntario_roles(self, voluntario_id: str) -> list[str]:
        self.captured_calls.append(("list_voluntario_roles", voluntario_id))
        return []

    def assign_voluntario_role(self, voluntario_id: str, rol: str) -> Voluntario:
        from app.core.data_access import UniqueViolationError

        self.captured_calls.append(("assign_voluntario_role", voluntario_id, rol))
        if self.assign_unique_violation:
            raise UniqueViolationError("unique constraint violation")
        if self.assign_error:
            raise self.assign_error
        return self.get_row or Voluntario(id=voluntario_id, voluntario="Ana", activo=True)

    def remove_voluntario_role(self, voluntario_id: str, rol: str) -> Voluntario:
        self.captured_calls.append(("remove_voluntario_role", voluntario_id, rol))
        if self.remove_error:
            raise self.remove_error
        return self.get_row or Voluntario(id=voluntario_id, voluntario="Ana", activo=True)


@pytest.fixture
def voluntarios_spy() -> _VoluntariosPortSpy:
    spy = _VoluntariosPortSpy()

    def _spy_factory() -> VoluntariosPort:
        return spy

    app.dependency_overrides[get_voluntarios_port] = _spy_factory
    yield spy
    app.dependency_overrides.pop(get_voluntarios_port, None)


def _key_user_session() -> str:
    from app.core.config import get_settings

    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-voluntarios",
        },
        secret=get_settings().session_secret,
    )
    return token


def _reader_session() -> str:
    from app.core.config import get_settings

    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-voluntarios",
        },
        secret=get_settings().session_secret,
    )
    return token


def _install(client: httpx.AsyncClient, token: str) -> None:
    client.cookies.set(session_cookie_name(), token)


# --- RBAC (issue #144) ----------------------------------------------------


async def test_add_role_rejects_reader(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
    auth_rol_spy: _AuthRolSqlExecutor,
) -> None:
    """Reader rol gets 403 on POST /voluntarios/{id}/roles/add (issue #144).

    Issue #1041: this test needs the same per-test SQL spy as the
    reader-403 tests in ``tests/test_voluntarios_routes.py`` — the
    conftest default spy hardcodes ``key_user`` for the reval so the
    contract cannot be observed against it. The :fixture:`auth_rol_spy`
    fixture later in this file provides that seam. Mirrors the closed
    PR #1033 / commit 4a9401b precedent.
    """
    auth_rol_spy.auth_reval_rol = "reader"
    _install(client, _reader_session())
    response = await make_csrf_request(
        client, "POST", "/voluntarios/v-1/roles/add",
        form_data={"rol": "intake"},
    )
    assert response.status_code == 403
    assert voluntarios_spy.captured_calls == []


async def test_remove_role_rejects_reader(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
    auth_rol_spy: _AuthRolSqlExecutor,
) -> None:
    """Reader rol gets 403 on POST /voluntarios/{id}/roles/remove (issue #144).

    See :func:`test_add_role_rejects_reader` for the issue #1041
    isolation context. Mirrors the closed PR #1033 / commit 4a9401b
    precedent.
    """
    auth_rol_spy.auth_reval_rol = "reader"
    _install(client, _reader_session())
    response = await make_csrf_request(
        client, "POST", "/voluntarios/v-1/roles/remove",
        form_data={"rol": "intake"},
    )
    assert response.status_code == 403
    assert voluntarios_spy.captured_calls == []


# --- Add role -------------------------------------------------------------


async def test_add_role_calls_port(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """POST /voluntarios/{id}/roles/add calls ``assign_voluntario_role``."""
    _install(client, _key_user_session())
    response = await make_csrf_request(
        client, "POST", "/voluntarios/v-1/roles/add",
        form_data={"rol": "intake"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/voluntarios/v-1"
    assert (
        "assign_voluntario_role", "v-1", "intake"
    ) in voluntarios_spy.captured_calls


async def test_add_role_unique_violation_returns_422(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """Duplicate role assignment returns 422 with error message."""
    voluntarios_spy.assign_unique_violation = True
    _install(client, _key_user_session())
    response = await make_csrf_request(
        client, "POST", "/voluntarios/v-1/roles/add",
        form_data={"rol": "intake"},
    )
    assert response.status_code == 422
    assert "ya tiene ese rol asignado" in response.text


# --- Remove role ----------------------------------------------------------


async def test_remove_role_calls_port(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """POST /voluntarios/{id}/roles/remove calls ``remove_voluntario_role``."""
    _install(client, _key_user_session())
    response = await make_csrf_request(
        client, "POST", "/voluntarios/v-1/roles/remove",
        form_data={"rol": "intake"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/voluntarios/v-1"
    assert (
        "remove_voluntario_role", "v-1", "intake"
    ) in voluntarios_spy.captured_calls


# ---------------------------------------------------------------------------
# Per-test SQL spy for the auth revalidation SELECT (issue #1041, mirror of
# PR #1033 commit 4a9401b)
# ---------------------------------------------------------------------------
# The conftest default spy hardcodes ``rol='key_user'`` for every auth
# reval query, so reader-403 tests can never observe a 403 against it.
# The seam below lets the two reader-403 tests above override the rol the
# reval returns, so the per-request revalidation SELECT echoes the cookie
# role and ``require_permission`` actually denies the request.
# ---------------------------------------------------------------------------


class _AuthRolSqlExecutor(LocalPostgresExecutor):
    """SQL executor that honors a per-test ``auth_reval_rol``.

    Mirrors :class:`tests.test_voluntarios_routes._AuthRolSqlExecutor`
    so reader / unknown / developer cases observe the rol the cookie
    carries rather than the conftest default. The route handlers in this
    file go through the hexagonal ``voluntarios_port``, so any non-auth
    SQL fired by the route would be a regression we want to surface as an
    error here rather than let it pass.
    """

    def __init__(self) -> None:
        import httpx as _httpx
        self._client = _httpx.Client(base_url="https://auth-rol-spy.example")
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval  # type: ignore[no-any-return]
        raise AssertionError(
            f"voluntarios role routes MUST NOT execute SQL directly: {query!r}"
        )

    def close(self) -> None:
        pass  # no-op for spy


@pytest.fixture
def auth_rol_spy() -> _AuthRolSqlExecutor:
    """Install :class:`_AuthRolSqlExecutor` as the auth reval seam.

    Clears the in-process auth cache (issues #143/#145/#262/#287) so a
    ``rocio@example.com`` verdict minted by an earlier test cannot leak
    into the reader-403 path; tests that exercise the reader path assign
    ``auth_rol_spy.auth_reval_rol = "reader"`` BEFORE installing the
    reader cookie, mirroring the established pattern in
    ``tests/test_voluntarios_routes.py`` and ``tests/test_animals_routes.py``.
    """
    from app.core import auth_cache

    auth_cache.invalidate_all()
    spy = _AuthRolSqlExecutor()
    app.state.sql_executor = spy
    app.dependency_overrides[get_local_postgres_executor_dep] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_local_postgres_executor_dep, None)
    app.state.__dict__.pop("sql_executor", None)
    auth_cache.invalidate_all()
