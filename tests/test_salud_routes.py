"""Route-layer tests for HEALTH-04 salud (CRUD).

Mirrors ``tests/test_sanidad_routes.py`` — patches service functions
via monkeypatch rather than replacing execute_sql.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_insforge_client_dep
from app.core.config import get_settings
from app.core.data_access import BackendError
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.salud import service as salud_service
from tests.conftest import make_csrf_request


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly."""

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx
        self._client = _httpx.Client(base_url="https://spy.example")

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        # Only allow auth_reval queries (used by require_authorized_user)
        if "usuarios_autorizados" in query and "email" in query.lower():
            return [{"id": "u-ana", "email": "ana@example.com", "rol": "key_user", "is_authorized": True}]
        raise AssertionError(f"routes must not execute SQL directly: {query!r}")


@pytest.fixture
def route_client() -> _NoSqlRouteClient:
    spy = _NoSqlRouteClient()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    app.dependency_overrides[get_insforge_client_dep] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)
    app.dependency_overrides.pop(get_insforge_client_dep, None)


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-salud",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_reader(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-salud",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _terapia() -> salud_service.Terapia:
    return salud_service.Terapia(
        id="terapia-123",
        animal_id="animal-123",
        voluntario_id="vol-123",
        fecha="2026-07-04",
        descripcion="Sesión de fisioterapia",
        created_at="2026-07-04T10:00:00Z",
        updated_at="2026-07-04T10:00:00Z",
        activo=True,
    )


def _recomendacion() -> salud_service.Recomendacion:
    return salud_service.Recomendacion(
        id="rec-123",
        terapia_id="terapia-123",
        fecha="2026-07-04",
        texto="Aplicar hielo 20 min/día",
        completada=False,
        created_at="2026-07-04T10:00:00Z",
        activo=True,
    )


# --- 1. Auth guard ----------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/terapias"),
        ("GET", "/terapias/new"),
        ("POST", "/terapias"),
        ("GET", "/terapias/terapia-123"),
        ("GET", "/terapias/terapia-123/edit"),
        ("POST", "/terapias/terapia-123/update"),
        ("POST", "/terapias/terapia-123/delete"),
        ("GET", "/terapias/terapia-123/recomendaciones"),
        ("POST", "/terapias/terapia-123/recomendaciones"),
        ("PATCH", "/recomendaciones/rec-123"),
        ("DELETE", "/recomendaciones/rec-123"),
    ],
)
async def test_salud_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every salud endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. Write endpoints reject reader with 403 --------------------------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        ("POST", "/terapias", {"animal_id": "a", "voluntario_id": "v", "fecha": "2026-07-04"}),
        ("POST", "/terapias/terapia-123/update", {"animal_id": "a", "voluntario_id": "v", "fecha": "2026-07-04"}),
        ("POST", "/terapias/terapia-123/delete", None),
        ("POST", "/terapias/terapia-123/recomendaciones", {"fecha": "2026-07-04", "texto": "texto"}),
        ("PATCH", "/recomendaciones/rec-123", None),
        ("DELETE", "/recomendaciones/rec-123", None),
    ],
)
async def test_salud_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient, method: str, path: str, form_data: dict[str, Any] | None
) -> None:
    """Write endpoints require ``WRITE_SALUD``; reader -> 403."""
    _login_as_reader(client)
    response = await make_csrf_request(
        client, method, path, form_data=form_data
    )
    assert response.status_code == 403


# --- 3. terapia CRUD via monkeypatch -----------------------------------------


async def test_list_terapias_ok(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias returns 200 with terapias list."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "list_terapias",
        lambda _c, *, animal_id=None: [_terapia()],
    )
    response = await client.get("/terapias", follow_redirects=True)
    assert response.status_code == 200


async def test_create_terapia_201_and_redirect(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias creates and redirects to detail."""
    _login_as_key_user(client)
    created = _terapia()
    monkeypatch.setattr(
        salud_service, "create_terapia",
        lambda _c, params, **kw: created,
    )
    response = await make_csrf_request(
        client, "POST", "/terapias",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "vol-123",
            "fecha": "2026-07-04",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias/terapia-123"


async def test_create_terapia_voluntario_inactivo_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias with inactive voluntario returns 422."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "create_terapia",
        lambda _c, params, **kw: (_ for _ in ()).throw(
            ValueError("voluntario_id debe apuntar a un voluntario activo")
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "vol-123",
            "fecha": "2026-07-04",
        },
    )
    assert response.status_code == 422


async def test_get_terapia_detail_404(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id} returns 404 when not found."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_terapia_by_id",
        lambda _c, _id: None,
    )
    response = await client.get("/terapias/not-found", follow_redirects=True)
    assert response.status_code == 404


async def test_get_terapia_detail_includes_recomendaciones(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id} returns 200 with recomendaciones."""
    _login_as_key_user(client)
    terapia = _terapia()
    rec = _recomendacion()
    monkeypatch.setattr(salud_service, "get_terapia_by_id", lambda _c, _id: terapia)
    monkeypatch.setattr(
        salud_service, "list_recomendaciones",
        lambda _c, _tid: [rec],
    )
    response = await client.get("/terapias/terapia-123", follow_redirects=True)
    assert response.status_code == 200


async def test_delete_terapia_409_when_pending_recomendaciones(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE /terapias/{id} returns 409 when pending recommendations exist."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "delete_terapia",
        lambda _c, _id, **kw: (_ for _ in ()).throw(
            salud_service.TerapiaHasPendingRecomendaciones(
                "terapia terapia-123 tiene recomendaciones pendientes"
            )
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/delete"
    )
    assert response.status_code == 409


async def test_delete_terapia_success(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE /terapias/{id} soft-deletes and redirects to /terapias."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "delete_terapia",
        lambda _c, _id, **kw: True,
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/delete"
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias"


# --- 4. Recomendacion CRUD via monkeypatch ----------------------------------


async def test_create_recomendacion_creates_and_redirects(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/recomendaciones creates and redirects."""
    _login_as_key_user(client)
    rec = _recomendacion()
    monkeypatch.setattr(
        salud_service, "create_recomendacion",
        lambda _c, params, **kw: rec,
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/recomendaciones",
        form_data={"fecha": "2026-07-04", "texto": "Aplicar hielo"},
    )
    assert response.status_code == 303


async def test_complete_recomendacion_patched_and_redirects(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH /recomendaciones/{id} marks completada=true and redirects."""
    _login_as_key_user(client)
    rec = _recomendacion()
    completed = salud_service.Recomendacion(
        id=rec.id, terapia_id=rec.terapia_id, fecha=rec.fecha,
        texto=rec.texto, completada=True,
        created_at=rec.created_at, activo=rec.activo,
    )
    monkeypatch.setattr(
        salud_service, "complete_recomendacion",
        lambda _c, _id, **kw: completed,
    )
    response = await make_csrf_request(
        client, "PATCH", "/recomendaciones/rec-123"
    )
    assert response.status_code == 303


async def test_complete_recomendacion_not_found_404(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH /recomendaciones/{id} returns 404 when not found."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "complete_recomendacion",
        lambda _c, _id, **kw: (_ for _ in ()).throw(
            salud_service.RecomendacionNotFoundError("not found")
        ),
    )
    response = await make_csrf_request(
        client, "PATCH", "/recomendaciones/not-found"
    )
    assert response.status_code == 404


async def test_delete_recomendacion_soft_deletes_and_redirects(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE /recomendaciones/{id} soft-deletes and redirects."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_recomendacion_by_id",
        lambda _c, _id: _recomendacion(),
    )
    monkeypatch.setattr(
        salud_service, "delete_recomendacion",
        lambda _c, _id, **kw: True,
    )
    response = await make_csrf_request(
        client, "DELETE", "/recomendaciones/rec-123"
    )
    assert response.status_code == 303
    assert "/terapias/terapia-123" in response.headers["location"]


# --- 5. Uncovered form-render and CRUD paths ----------------------------------


async def test_new_terapia_form_ok(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """GET /terapias/new returns 200 with an empty form."""
    _login_as_key_user(client)
    response = await client.get("/terapias/new", follow_redirects=True)
    assert response.status_code == 200


async def test_edit_terapia_form_ok(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id}/edit returns 200 with prefilled form."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_terapia_by_id",
        lambda _c, _id: _terapia(),
    )
    response = await client.get("/terapias/terapia-123/edit", follow_redirects=True)
    assert response.status_code == 200


async def test_update_terapia_success_and_redirects(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/update updates and redirects to detail."""
    _login_as_key_user(client)
    updated = _terapia()
    monkeypatch.setattr(
        salud_service, "update_terapia",
        lambda _c, _id, params, **kw: updated,
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/update",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "vol-123",
            "fecha": "2026-07-05",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias/terapia-123"


async def test_update_terapia_422_on_fk_error(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/update returns 422 on FK validation error."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "update_terapia",
        lambda _c, _id, params, **kw: (_ for _ in ()).throw(
            ValueError("voluntario_id debe apuntar a un voluntario activo")
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/update",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "vol-inactive",
            "fecha": "2026-07-05",
        },
    )
    assert response.status_code == 422


async def test_list_recomendaciones_ok(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id}/recomendaciones returns 200 with list."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_terapia_by_id",
        lambda _c, _id: _terapia(),
    )
    monkeypatch.setattr(
        salud_service, "list_recomendaciones",
        lambda _c, _tid: [_recomendacion()],
    )
    response = await client.get(
        "/terapias/terapia-123/recomendaciones", follow_redirects=True
    )
    assert response.status_code == 200


async def test_create_recomendacion_terapia_not_found_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/recomendaciones returns 422 when terapia missing."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "create_recomendacion",
        lambda _c, params, **kw: (_ for _ in ()).throw(
            ValueError("terapia_id no existe")
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/recomendaciones",
        form_data={"fecha": "2026-07-04", "texto": "Aplicar hielo"},
    )
    assert response.status_code == 422


async def test_complete_recomendacion_backend_error_503(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH /recomendaciones/{id} returns 503 on BackendError."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "complete_recomendacion",
        lambda _c, _id, **kw: (_ for _ in ()).throw(
            BackendError(500, "connection refused")
        ),
    )
    response = await make_csrf_request(
        client, "PATCH", "/recomendaciones/rec-123"
    )
    assert response.status_code == 503


async def test_delete_recomendacion_not_found_404(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE /recomendaciones/{id} returns 404 when not found."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_recomendacion_by_id",
        lambda _c, _id: None,
    )
    response = await make_csrf_request(
        client, "DELETE", "/recomendaciones/not-found"
    )
    assert response.status_code == 404


async def test_delete_recomendacion_backend_error_503(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE /recomendaciones/{id} returns 503 on BackendError."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_recomendacion_by_id",
        lambda _c, _id: _recomendacion(),
    )
    monkeypatch.setattr(
        salud_service, "delete_recomendacion",
        lambda _c, _id, **kw: (_ for _ in ()).throw(
            BackendError(500, "connection refused")
        ),
    )
    response = await make_csrf_request(
        client, "DELETE", "/recomendaciones/rec-123"
    )
    assert response.status_code == 503


# --- 6. Remaining uncovered branches ------------------------------------------


async def test_edit_terapia_form_404_when_not_found(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id}/edit returns 404 when the terapia does not exist."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_terapia_by_id",
        lambda _c, _id: None,
    )
    response = await client.get("/terapias/not-found/edit", follow_redirects=True)
    assert response.status_code == 404


async def test_update_terapia_404_when_not_found(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/update returns 404 when the terapia does not exist."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "update_terapia",
        lambda _c, _id, params, **kw: None,
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/not-found/update",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "vol-123",
            "fecha": "2026-07-05",
        },
    )
    assert response.status_code == 404


async def test_create_terapia_backend_error_503(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias returns 503 when the backend raises BackendError."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "create_terapia",
        lambda _c, params, **kw: (_ for _ in ()).throw(
            BackendError(500, "connection refused")
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "vol-123",
            "fecha": "2026-07-04",
        },
    )
    assert response.status_code == 503


async def test_update_terapia_backend_error_503(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/update returns 503 when the backend raises BackendError."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "update_terapia",
        lambda _c, _id, params, **kw: (_ for _ in ()).throw(
            BackendError(500, "connection refused")
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/update",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "vol-123",
            "fecha": "2026-07-05",
        },
    )
    assert response.status_code == 503


async def test_delete_terapia_backend_error_503(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/delete returns 503 when BackendError is raised."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "delete_terapia",
        lambda _c, _id, **kw: (_ for _ in ()).throw(
            BackendError(500, "connection refused")
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/delete"
    )
    assert response.status_code == 503


async def test_list_recomendaciones_404_when_terapia_not_found(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id}/recomendaciones returns 404 when the terapia is missing."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "get_terapia_by_id",
        lambda _c, _id: None,
    )
    response = await client.get(
        "/terapias/not-found/recomendaciones", follow_redirects=True
    )
    assert response.status_code == 404


async def test_create_recomendacion_backend_error_503(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/recomendaciones returns 503 on BackendError."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        salud_service, "create_recomendacion",
        lambda _c, params, **kw: (_ for _ in ()).throw(
            BackendError(500, "connection refused")
        ),
    )
    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/recomendaciones",
        form_data={"fecha": "2026-07-04", "texto": "Aplicar hielo"},
    )
    assert response.status_code == 503
