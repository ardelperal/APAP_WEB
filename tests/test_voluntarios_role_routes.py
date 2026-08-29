"""Route-level tests for voluntarios role management (epic #420 VOL-02).

Tests the add/remove role POST endpoints:
- POST /voluntarios/{id}/roles/add — assigns role.
- POST /voluntarios/{id}/roles/remove — removes role.
- RBAC: reader rol receives 403 on both write endpoints (issue #144).
"""
from __future__ import annotations

import httpx
import pytest

from app.core.session import session_cookie_name, write_session
from app.main import app
from app.modules.voluntarios.di import get_voluntarios_port
from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort
from tests.conftest import make_csrf_request


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
) -> None:
    """Reader rol gets 403 on POST /voluntarios/{id}/roles/add."""
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
) -> None:
    """Reader rol gets 403 on POST /voluntarios/{id}/roles/remove."""
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
