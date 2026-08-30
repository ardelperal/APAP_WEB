"""Route-level tests for the voluntarios routes (epic #420 PR-B).

Covers the hexagonal wiring of routes to use cases via :func:`get_voluntarios_port`:
- GET/POST `/voluntarios` — list and create
- GET `/voluntarios/{id}` — detail
- POST `/voluntarios/{id}/deactivate` — soft-delete (TOCTOU fix)

RBAC (issue #144): reader rol is rejected with 403 on write endpoints.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.session import session_cookie_name, write_session
from app.main import app
from app.modules.voluntarios.di import get_voluntarios_port
from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort
from tests.conftest import make_csrf_request

# -------------------------------------------------------------------------------------------------
# Test port spy — captures all port method calls (hexagonal equivalent of the
# legacy execute_sql spy). Lets us assert the route calls exactly what it should
# and nothing else (no SELECT prior to UPDATE, etc.).
# -------------------------------------------------------------------------------------------------


class _VoluntariosPortSpy:
    """``VoluntariosPort`` spy that records calls and returns configurable data.

    Replaces the legacy ``execute_sql`` spy now that routes go through the
    hexagonal port instead of calling ``voluntarios_service`` directly.
    """

    def __init__(self) -> None:
        self.captured_calls: list[tuple[str, Any]] = []
        self.list_rows: list[Voluntario] = []
        self.get_row: Voluntario | None = None
        self.create_voluntario_row: Voluntario | None = None
        self.create_unique_violation = False
        self.deactivate_result = True
        self.deactivate_call_count = 0
        self.deactivate_rotating: list[bool] | None = None
        # For the auth revalidation SELECT inside the permission check.
        self.auth_reval_rol = "key_user"

    def list_voluntarios(self) -> list[Voluntario]:
        self.captured_calls.append(("list_voluntarios", None))
        return self.list_rows

    def get_voluntario_by_id(self, voluntario_id: str) -> Voluntario | None:
        self.captured_calls.append(("get_voluntario_by_id", voluntario_id))
        return self.get_row

    def create_voluntario(
        self,
        *,
        nombre: str,
        tel1: str | None = None,
        tel2: str | None = None,
        email: str | None = None,
        dni: str | None = None,
    ) -> Voluntario:
        from app.core.data_access import UniqueViolationError

        self.captured_calls.append(
            ("create_voluntario", {"nombre": nombre, "tel1": tel1, "tel2": tel2, "email": email, "dni": dni})
        )
        if self.create_unique_violation:
            raise UniqueViolationError("unique constraint violation: email")
        if self.create_voluntario_row is None:
            raise RuntimeError("unexpected call")
        return self.create_voluntario_row

    def deactivate_voluntario(self, voluntario_id: str) -> bool:
        self.captured_calls.append(("deactivate_voluntario", voluntario_id))
        self.deactivate_call_count += 1
        if self.deactivate_rotating is not None:
            idx = min(self.deactivate_call_count - 1, len(self.deactivate_rotating) - 1)
            return self.deactivate_rotating[idx]
        return self.deactivate_result

    def list_voluntario_roles(self, voluntario_id: str) -> list[str]:
        self.captured_calls.append(("list_voluntario_roles", voluntario_id))
        return []


# -------------------------------------------------------------------------------------------------
# FastAPI dependency override
# -------------------------------------------------------------------------------------------------


@pytest.fixture
def voluntarios_spy() -> _VoluntariosPortSpy:
    """Override ``get_voluntarios_port`` with a spy port.

    The spy captures every port method call so tests can assert the route
    invokes exactly the expected use case without extra round-trips.
    """
    spy = _VoluntariosPortSpy()

    def _spy_factory() -> VoluntariosPort:
        return spy

    app.dependency_overrides[get_voluntarios_port] = _spy_factory
    yield spy
    app.dependency_overrides.pop(get_voluntarios_port, None)


# -------------------------------------------------------------------------------------------------
# Session helpers
# -------------------------------------------------------------------------------------------------


def _write_key_user_session() -> str:
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


def _write_reader_session() -> str:
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


def _install_session(client: httpx.AsyncClient, session_token: str) -> None:
    client.cookies.set(session_cookie_name(), session_token)


# -------------------------------------------------------------------------------------------------
# RBAC: reader cannot write (issue #144)
# -------------------------------------------------------------------------------------------------


async def test_create_voluntario_rejects_reader_with_403(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """Reader rol receives 403 on POST /voluntarios (issue #144)."""
    voluntarios_spy.auth_reval_rol = "reader"
    _install_session(client, _write_reader_session())

    response = await make_csrf_request(
        client,
        "POST",
        "/voluntarios",
        form_data={"Voluntario": "Rocio"},
    )

    assert response.status_code == 403
    assert voluntarios_spy.captured_calls == []


async def test_deactivate_voluntario_rejects_reader_with_403(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """Reader rol receives 403 on POST /voluntarios/{id}/deactivate (issue #144)."""
    voluntarios_spy.auth_reval_rol = "reader"
    _install_session(client, _write_reader_session())

    response = await make_csrf_request(
        client,
        "POST",
        "/voluntarios/v-1/deactivate",
    )

    assert response.status_code == 403
    assert voluntarios_spy.captured_calls == []


# -------------------------------------------------------------------------------------------------
# Deactivate: exactly one port call, no SELECT prior (TOCTOU fix)
# -------------------------------------------------------------------------------------------------


async def test_deactivate_routes_calls_port_once(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """POST /voluntarios/{id}/deactivate calls ``deactivate_voluntario`` exactly once.

    No ``get_voluntario_by_id`` is called first (TOCTOU fix: the existence check
    is now inside the atomic UPDATE, not a separate SELECT).
    """
    _install_session(client, _write_key_user_session())

    response = await make_csrf_request(
        client,
        "POST",
        "/voluntarios/v-1/deactivate",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/voluntarios"
    deactivate_calls = [
        c for c in voluntarios_spy.captured_calls
        if c[0] == "deactivate_voluntario"
    ]
    assert len(deactivate_calls) == 1
    assert deactivate_calls[0][1] == "v-1"
    get_calls = [
        c for c in voluntarios_spy.captured_calls
        if c[0] == "get_voluntario_by_id"
    ]
    assert get_calls == [], "no SELECT prior to UPDATE (TOCTOU fix)"


async def test_deactivate_routes_404_when_inactive(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """Second deactivate returns 404 (row already inactive)."""
    voluntarios_spy.deactivate_rotating = [True, False]
    _install_session(client, _write_key_user_session())

    first = await make_csrf_request(
        client,
        "POST",
        "/voluntarios/v-1/deactivate",
    )
    second = await make_csrf_request(
        client,
        "POST",
        "/voluntarios/v-1/deactivate",
    )

    assert first.status_code == 303
    assert second.status_code == 404


async def test_deactivate_routes_404_when_not_found(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """Inexistent voluntario returns 404."""
    voluntarios_spy.deactivate_result = False
    _install_session(client, _write_key_user_session())

    response = await make_csrf_request(
        client,
        "POST",
        "/voluntarios/no-such-id/deactivate",
    )

    assert response.status_code == 404


# -------------------------------------------------------------------------------------------------
# Detail: calls get_voluntario_by_id + list_voluntario_roles
# -------------------------------------------------------------------------------------------------


async def test_detail_calls_port_methods(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """GET /voluntarios/{id} calls ``get_voluntario_by_id`` and ``list_voluntario_roles``."""
    voluntarios_spy.get_row = Voluntario(
        id="v-1", voluntario="Ana Garcia", activo=True
    )
    _install_session(client, _write_key_user_session())

    response = await make_csrf_request(
        client,
        "GET",
        "/voluntarios/v-1",
    )

    assert response.status_code == 200
    # Must call both port methods (detail + roles).
    assert ("get_voluntario_by_id", "v-1") in voluntarios_spy.captured_calls
    assert ("list_voluntario_roles", "v-1") in voluntarios_spy.captured_calls


async def test_detail_404_when_not_found(
    client: httpx.AsyncClient,
    voluntarios_spy: _VoluntariosPortSpy,
) -> None:
    """GET /voluntarios/{id} returns 404 when the row does not exist."""
    voluntarios_spy.get_row = None
    _install_session(client, _write_key_user_session())

    response = await make_csrf_request(
        client,
        "GET",
        "/voluntarios/no-such-id",
    )

    assert response.status_code == 404
