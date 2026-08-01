"""Route-layer tests for HEALTH-05 terapias + recomendaciones (issue #54).

Mirrors ``tests/test_sanidad_routes.py`` pattern. Routes are pure HTTP
/ auth / template glue. The fixture ``_TerapiaRouteClient`` enforces
the AGENTS.md layer-boundary rule (no ``client.execute_sql`` in routes).

Auth model: GET endpoints use ``require_authorized_user``; write endpoints
(POST create / update / delete / complete) use ``require_writer_user``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_insforge_client_dep
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.sanidad import terapia_service as terapia_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _TerapiaRouteClient(InsForgeClient):
    """Client spy: routes must not call execute_sql directly."""

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval
        raise AssertionError(f"routes must not execute SQL directly: {query!r}")


@pytest.fixture
def terapia_route_client() -> _TerapiaRouteClient:
    spy = _TerapiaRouteClient()
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
            "csrf_token": "test-csrf-token-terapia",
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
            "csrf_token": "test-csrf-token-terapia",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _terapia() -> terapia_service.Terapia:
    return terapia_service.Terapia(
        id="terapia-123",
        animal_id="animal-123",
        fecha="2026-07-15",
        voluntario_id="voluntario-123",
        descripcion="Sesión de fisioterapia",
        created_at="2026-07-15T10:00:00Z",
        updated_at="2026-07-15T10:00:00Z",
        activo=True,
    )


def _recomendacion() -> terapia_service.Recomendacion:
    return terapia_service.Recomendacion(
        id="rec-123",
        terapia_id="terapia-123",
        fecha="2026-07-20",
        texto="Continuar con ejercicios",
        completada=False,
        created_at="2026-07-20T10:00:00Z",
        activo=True,
    )


# --- 1. Auth guard --------------------------------------------------------


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
        ("POST", "/terapias/terapia-123/recomendaciones"),
        ("POST", "/recomendaciones/rec-123/complete"),
        ("POST", "/recomendaciones/rec-123/delete"),
    ],
)
async def test_terapia_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every terapia endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. require_writer_user: writes reject reader with 403 ----------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        ("POST", "/terapias", {"animal_id": "a", "voluntario_id": "v", "fecha": "2026-07-15"}),
        ("POST", "/terapias/terapia-123/update", {"animal_id": "a", "voluntario_id": "v", "fecha": "2026-07-15"}),
        ("POST", "/terapias/terapia-123/delete", None),
        ("POST", "/terapias/terapia-123/recomendaciones", {"fecha": "2026-07-20", "texto": "text"}),
        ("POST", "/recomendaciones/rec-123/complete", None),
        ("POST", "/recomendaciones/rec-123/delete", None),
    ],
)
async def test_terapia_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """Reader rol is forbidden on every terapia write route."""
    terapia_route_client.auth_reval_rol = "reader"
    _login_as_reader(client)

    def _never_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            f"reader POST MUST NOT reach the service; got {args=} {kwargs=}"
        )

    monkeypatch.setattr(terapia_service, "create_terapia", _never_called)
    monkeypatch.setattr(terapia_service, "update_terapia", _never_called)
    monkeypatch.setattr(terapia_service, "delete_terapia", _never_called)
    monkeypatch.setattr(terapia_service, "create_recomendacion", _never_called)
    monkeypatch.setattr(terapia_service, "complete_recomendacion", _never_called)
    monkeypatch.setattr(terapia_service, "delete_recomendacion", _never_called)

    response = await make_csrf_request(
        client, method, path, form_data=form_data
    )
    assert response.status_code == 403


# --- 3. Create terapia ----------------------------------------------------


async def test_create_terapia_redirects_to_detail(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias creates the terapia and redirects to the detail view."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    created = _terapia()

    def _create(
        client: Any, params: Any, *, actor_user_id: Any = None
    ) -> terapia_service.Terapia:
        return created

    monkeypatch.setattr(terapia_service, "create_terapia", _create)

    response = await make_csrf_request(
        client,
        "POST",
        "/terapias",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "voluntario-123",
            "fecha": "2026-07-15",
            "descripcion": "Sesión de fisioterapia",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias/terapia-123"


async def test_create_terapia_renders_422_on_validation_error(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias re-renders the form with 422 on ValueError."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    def _create_fail(
        client: Any, params: Any, *, actor_user_id: Any = None
    ) -> terapia_service.Terapia:
        raise ValueError("animal_id must reference an active animal")

    monkeypatch.setattr(terapia_service, "create_terapia", _create_fail)

    response = await make_csrf_request(
        client,
        "POST",
        "/terapias",
        form_data={
            "animal_id": "nonexistent",
            "voluntario_id": "voluntario-123",
            "fecha": "2026-07-15",
        },
    )
    assert response.status_code == 422


# --- 4. List terapias -----------------------------------------------------


async def test_list_terapias_renders_page(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias renders the list template."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    def _list(
        client: Any, *, animal_id: Any = None
    ) -> list[terapia_service.Terapia]:
        return [_terapia()]

    monkeypatch.setattr(terapia_service, "list_terapias", _list)

    response = await client.request("GET", "/terapias")
    assert response.status_code == 200


# --- 5. Terapia detail ----------------------------------------------------


async def test_terapia_detail_renders_with_recomendaciones(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id} includes recomendaciones in context."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    terapia = _terapia()
    recomendacion = _recomendacion()

    def _get(client: Any, terapia_id: str) -> terapia_service.Terapia | None:
        if terapia_id == "terapia-123":
            return terapia
        return None

    def _list_recs(
        client: Any, terapia_id: str
    ) -> list[terapia_service.Recomendacion]:
        if terapia_id == "terapia-123":
            return [recomendacion]
        return []

    monkeypatch.setattr(terapia_service, "get_terapia", _get)
    monkeypatch.setattr(terapia_service, "list_recomendaciones", _list_recs)

    response = await client.request("GET", "/terapias/terapia-123")
    assert response.status_code == 200


async def test_terapia_detail_404_when_not_found(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /terapias/{id} returns 404 when id does not exist."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    monkeypatch.setattr(terapia_service, "get_terapia", lambda *a, **kw: None)

    response = await client.request("GET", "/terapias/nonexistent")
    assert response.status_code == 404


# --- 6. Update terapia -----------------------------------------------------


async def test_update_terapia_redirects_to_detail(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/update redirects to detail on success."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    updated = _terapia()

    def _update(
        client: Any, terapia_id: str, params: Any, *, actor_user_id: Any = None
    ) -> terapia_service.Terapia | None:
        return updated

    monkeypatch.setattr(terapia_service, "update_terapia", _update)

    response = await make_csrf_request(
        client,
        "POST",
        "/terapias/terapia-123/update",
        form_data={
            "animal_id": "animal-123",
            "voluntario_id": "voluntario-123",
            "fecha": "2026-07-15",
        },
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias/terapia-123"


# --- 7. Delete terapia ----------------------------------------------------


async def test_delete_terapia_redirects_to_list(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/delete soft-deletes and redirects to /terapias."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    def _delete(
        client: Any, terapia_id: str, *, actor_user_id: Any = None
    ) -> bool:
        return True

    monkeypatch.setattr(terapia_service, "delete_terapia", _delete)

    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/delete"
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias"


async def test_delete_terapia_409_when_pending_recomendaciones(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE with pending recommendations returns 409."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    terapia = _terapia()
    rec = _recomendacion()

    def _get(client: Any, terapia_id: str) -> terapia_service.Terapia | None:
        return terapia

    def _list_recs(
        client: Any, terapia_id: str
    ) -> list[terapia_service.Recomendacion]:
        return [rec]

    def _delete_fail(
        client: Any, terapia_id: str, *, actor_user_id: Any = None
    ) -> bool:
        raise terapia_service.TerapiaDeleteError(
            "No se puede borrar la terapia: tiene recomendaciones pendientes"
        )

    monkeypatch.setattr(terapia_service, "delete_terapia", _delete_fail)
    monkeypatch.setattr(terapia_service, "get_terapia", _get)
    monkeypatch.setattr(terapia_service, "list_recomendaciones", _list_recs)

    response = await make_csrf_request(
        client, "POST", "/terapias/terapia-123/delete"
    )
    assert response.status_code == 409


# --- 8. Create recomendacion ----------------------------------------------


async def test_create_recomendacion_redirects_to_terapia_detail(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /terapias/{id}/recomendaciones redirects to terapia detail."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    rec = _recomendacion()

    def _create_rec(
        client: Any,
        terapia_id: str,
        params: Any,
        *,
        actor_user_id: Any = None,
    ) -> terapia_service.Recomendacion:
        return rec

    monkeypatch.setattr(terapia_service, "create_recomendacion", _create_rec)

    response = await make_csrf_request(
        client,
        "POST",
        "/terapias/terapia-123/recomendaciones",
        form_data={"fecha": "2026-07-20", "texto": "Continuar con ejercicios"},
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias/terapia-123"


# --- 9. Complete recomendacion --------------------------------------------


async def test_complete_recomendacion_redirects_to_terapia_detail(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /recomendaciones/{id}/complete marks done and redirects."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    completed = _recomendacion()

    def _complete(
        client: Any, recomendacion_id: str, *, actor_user_id: Any = None
    ) -> terapia_service.Recomendacion | None:
        return completed

    monkeypatch.setattr(terapia_service, "complete_recomendacion", _complete)

    # Need to also mock execute_sql for the terapia_id lookup
    monkeypatch.setattr(
        terapia_route_client,
        "execute_sql",
        lambda q, p=None: [{"terapia_id": "terapia-123"}]
        if "recomendaciones" in q
        else auth_reval_rows(q, p),
    )

    response = await make_csrf_request(
        client, "POST", "/recomendaciones/rec-123/complete"
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/terapias/terapia-123"


# --- 10. Delete recomendacion --------------------------------------------


async def test_delete_recomendacion_redirects_to_terapia_detail(
    client: httpx.AsyncClient,
    terapia_route_client: _TerapiaRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /recomendaciones/{id}/delete soft-deletes and redirects."""
    _login_as_key_user(client)
    terapia_route_client.auth_reval_rol = "key_user"

    def _delete(
        client: Any, recomendacion_id: str, *, actor_user_id: Any = None
    ) -> bool:
        return True

    monkeypatch.setattr(terapia_service, "delete_recomendacion", _delete)
    monkeypatch.setattr(
        terapia_route_client,
        "execute_sql",
        lambda q, p=None: [{"terapia_id": "terapia-123"}]
        if "recomendaciones" in q
        else auth_reval_rows(q, p),
    )

    response = await make_csrf_request(
        client, "POST", "/recomendaciones/rec-123/delete"
    )
    assert response.status_code == 303
