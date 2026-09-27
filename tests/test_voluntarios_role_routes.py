"""Route-level tests for voluntarios role management (epic #420 VOL-02).

Tests the add/remove role POST endpoints:
- POST /voluntarios/{id}/roles/add — assigns role.
- POST /voluntarios/{id}/roles/remove — removes role.
- RBAC: reader rol receives 403 on both write endpoints (issue #144).

This file also hosts the issue #1019 regression tests for
``PATCH /adopciones/{id}/seguimiento``: that route was reachable by
reader/unknown role because it used ``require_authorized_user`` only.
The fix moves it to ``require_permission(WRITE_ADOPCIONES)`` and the
tests in section ``#1019 — seguimiento role guards`` pin the contract.
The fixture ``_AuthRolSqlExecutor`` overrides the conftest's default
SQL spy with one that honors the per-test ``auth_reval_rol`` so the
seam required by ``require_authorized_user`` matches the cookie role.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.di.local_postgres_di import get_local_postgres_executor_dep
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app
from app.modules.adopciones import service as adopciones_service
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

    Issue #1033: this test needs the same per-test SQL spy as the
    reader-403 tests in ``tests/test_voluntarios_routes.py`` — the
    conftest default spy hardcodes ``key_user`` for the reval so the
    contract cannot be observed against it. The :fixture:`auth_rol_spy`
    fixture later in this file provides that seam.
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

    See :func:`test_add_role_rejects_reader` for the issue #1033
    isolation context.
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
# #1019 — seguimiento role guards (PATCH /adopciones/{id}/seguimiento)
# ---------------------------------------------------------------------------
# The seguimiento state transition used ``require_authorized_user`` only,
# which never rejects unknown or ``reader`` role strings. The fix moves
# it to ``require_permission(WRITE_ADOPCIONES)`` so the matrix covers it;
# the tests below pin the contract.
# ---------------------------------------------------------------------------


class _AuthRolSqlExecutor(LocalPostgresExecutor):
    """SQL executor that echoes the cookie's rol on the revalidation SELECT.

    The conftest default returns ``key_user`` for every reval, masking
    reader-403 regressions — exactly the bug #1019 closes. This fixture
    mirrors ``tests/test_adopciones_routes.py::_NoSqlRouteClient`` (issue
    #143 seam).
    """

    def __init__(self) -> None:
        import httpx as _httpx
        self._client = _httpx.Client(base_url="https://auth-rol-spy.example")
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):
        reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if reval is not None:
            return reval  # type: ignore[no-any-return]
        raise AssertionError(
            f"seguimiento route MUST NOT execute SQL directly: {query!r}"
        )

    def close(self) -> None:
        pass  # no-op for spy


@pytest.fixture
def auth_rol_spy() -> _AuthRolSqlExecutor:
    """Install the per-role SQL spy and drop the auth cache between tests.

    The per-role email keeps the email-keyed ``in_process`` auth cache
    (issue #143) from cross-polluting between reader, unknown, developer
    and key_user cases in this file.
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


def _install_role(token_value: str) -> str:
    """Mint a session cookie whose rol is ``token_value``."""
    from app.core.config import get_settings
    token = write_session(
        {
            "email": f"op-{token_value}@example.com",
            "rol": token_value,
            "user_id": f"u-op-{token_value}",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-seguimiento",
        },
        secret=get_settings().session_secret,
    )
    return token


def _patch_cookie(client: httpx.AsyncClient, rol: str) -> None:
    """Install a session cookie for ``rol``; CSRF token stays fixed."""
    client.cookies.set(session_cookie_name(), _install_role(rol))


_PATCH_SEGUIMIENTO_URL = "/adopciones/adop-123/seguimiento"
_PATCH_SEGUIMIENTO_FORM = {"action": "marcar_entregado"}
_PATCH_SEGUIMIENTO_CSRF = "test-csrf-token-seguimiento"


@pytest.mark.parametrize(
    ("rol", "expected_status", "expected_location"),
    [
        ("reader", 403, None),  # matrix denies (legacy reader branch)
        ("ghost_role", 403, None),  # matrix denies (unknown role branch)
        ("key_user", 303, "/adopciones/adop-123"),  # legacy writer preserved
        ("developer", 303, "/adopciones/adop-123"),  # legacy writer preserved
    ],
)
async def test_patch_seguimiento_role_guard_matrix(
    client: httpx.AsyncClient,
    auth_rol_spy: _AuthRolSqlExecutor,
    monkeypatch: pytest.MonkeyPatch,
    rol: str,
    expected_status: int,
    expected_location: str | None,
) -> None:
    """Issue #1019: PATCH /adopciones/{id}/seguimiento follows the matrix.

    Parametrized over 4 roles: reader/unknown denied 403, key_user /
    developer allowed 303 to detail. Reader and unknown role strings
    reach ``require_permission`` because the conftest spy echoes the
    cookie role (no AuthorizedUser mapping shadows the unknown string —
    the bypass below patches both the use case module and the auth
    shim that captured the original function at import time).
    """
    auth_rol_spy.auth_reval_rol = rol
    _patch_cookie(client, rol)

    if rol == "ghost_role":
        # Bypass AuthorizedUser.from_row's silent Rol.KEY_USER fallback
        # so the route guard actually sees an unknown role string.
        from app.core import auth as _auth_shim
        from app.core.application.auth import get_user_by_email as _uc_get
        from app.core.domain.auth import user as _user_domain

        class _UnknownRol(str):
            @property
            def value(self) -> str:  # type: ignore[override]
                return str(self)

        def _fake(port: Any, email: str) -> Any:
            return _user_domain.AuthorizedUser(
                id="u-reval", email=email, rol=_UnknownRol(rol),
                active=True, added_by=None, added_at=None,
            )

        monkeypatch.setattr(_uc_get, "get_user_by_email", _fake)
        monkeypatch.setattr(_auth_shim, "_get_user_by_email_use_case", _fake)

    def _never_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            f"PATCH MUST NOT reach the service for rol={rol!r}; got {args=} {kwargs=}"
        )

    # Only deny cases must NOT reach the service. Allow cases need the
    # service to return a non-error outcome (303 redirect).
    if expected_status == 403:
        monkeypatch.setattr(
            adopciones_service, "transition_seguimiento_for_route", _never_called
        )
    else:
        monkeypatch.setattr(
            adopciones_service,
            "transition_seguimiento_for_route",
            lambda *_a, **_kw: None,  # success path → 303 redirect
        )

    response = await make_csrf_request(
        client,
        "PATCH",
        _PATCH_SEGUIMIENTO_URL,
        form_data=_PATCH_SEGUIMIENTO_FORM,
        csrf_token=_PATCH_SEGUIMIENTO_CSRF,
    )
    assert response.status_code == expected_status, (
        f"rol={rol!r}: expected {expected_status}, got {response.status_code} "
        f"on body {response.text!r}"
    )
    if expected_location is not None:
        assert response.headers["location"] == expected_location
