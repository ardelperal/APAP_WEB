"""Route-layer tests for HEALTH-01 sanidad (CRUD).

Mirror of ``tests/test_adopciones_routes.py`` and
``tests/test_entradas_routes.py``: routes are pure HTTP / auth /
template glue. The fixture ``_NoSqlRouteClient`` enforces the
AGENTS.md layer-boundary rule (no ``client.execute_sql`` in routes).
All data access goes through ``app.modules.sanidad.service``.

Auth model (issue #144): GET endpoints use ``require_authorized_user``;
write endpoints (POST create / update / delete) use
``require_writer_user`` which composes on
``require_authorized_user`` and rejects the ``reader`` rol with 403
BEFORE the handler runs.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_insforge_client_dep
from app.core.config import get_settings
from app.core.insforge import InsForgeClient, InsForgeError
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.sanidad import service as sanidad_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly.

    Mirrors the same pattern used in ``tests/test_adopciones_routes.py``:
    routes own no SQL, they delegate to the service. If a route ever
    calls ``client.execute_sql``, the spy raises AssertionError and the
    failing test names the offending query.
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user``; reader
        # rejection tests set this to ``reader`` so
        # ``require_writer_user`` produces 403 BEFORE any handler SQL.
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        # Issue #143: require_authorized_user revalidates authorization per
        # request via the get_user_by_email service; that SELECT flows
        # through this client and is allowed. Any OTHER direct SQL from a
        # route handler still violates the "cero SQL en routes" contract.
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval
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
    """Mint a session cookie with a known CSRF token bound to it."""
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-sanidad",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Install a reader session cookie; reader MUST be 403 on writes (issue #144)."""
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-sanidad",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _actuacion() -> sanidad_service.ActuacionSanitaria:
    """Canonical ActuacionSanitaria fixture for assertions."""
    return sanidad_service.ActuacionSanitaria(
        id="actu-123",
        animal_id="animal-123",
        fecha="2026-07-04",
        tipo_actuacion_id=None,
        veterinario="Dra. Pérez",
        observaciones="Vacuna anual",
        voluntario_id=None,
        material_utilizado="Nobivac Rabia",
        fecha_alta="2026-07-04T10:00:00Z",
        updated_at="2026-07-04T10:00:00Z",
        activo=True,
    )


# --- 1. Auth guard: every endpoint requires a session ---------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/sanidad"),
        ("GET", "/sanidad/new"),
        ("POST", "/sanidad"),
        ("GET", "/sanidad/actu-123"),
        ("GET", "/sanidad/actu-123/edit"),
        ("POST", "/sanidad/actu-123/update"),
        ("POST", "/sanidad/actu-123/delete"),
    ],
)
async def test_sanidad_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every sanidad endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. require_writer_user: writes reject reader with 403 ----------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        ("POST", "/sanidad", {"animal_id": "a", "fecha": "2026-07-04"}),
        ("POST", "/sanidad/actu-123/update", {"animal_id": "a", "fecha": "2026-07-04"}),
        ("POST", "/sanidad/actu-123/delete", None),
    ],
)
async def test_sanidad_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """Reader rol is forbidden on every sanidad write route (issue #144)."""
    route_client.auth_reval_rol = "reader"
    _login_as_reader(client)

    def _never_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            f"reader POST MUST NOT reach the service; got {args=} {kwargs=}"
        )

    monkeypatch.setattr(
        sanidad_service, "create_actuacion_sanitaria", _never_called
    )
    monkeypatch.setattr(
        sanidad_service, "update_actuacion_sanitaria", _never_called
    )
    monkeypatch.setattr(
        sanidad_service, "delete_actuacion_sanitaria", _never_called
    )

    response = await make_csrf_request(
        client, method, path, form_data=form_data
    )

    assert response.status_code == 403, (
        f"reader rol MUST be rejected on write routes; got {response.status_code} "
        f"on {method} {path}"
    )
    assert "Permisos insuficientes" in response.text


# --- 3. Form rendering: csrf_token present on new + edit -----------------


async def test_new_actuacion_form_renders_with_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /sanidad/new renders the form with csrf_token + catalogos_pruebas."""
    _login_as_key_user(client)

    def _catalogos(_client: Any) -> list[dict[str, Any]]:
        return [
            {"id": "cat-1", "codigo": "Rabia", "nombre": "Rabia", "especie": "ambos"},
            {"id": "cat-2", "codigo": "Esterilización", "nombre": "Esterilización", "especie": "ambos"},
        ]

    monkeypatch.setattr(
        sanidad_service, "list_catalogos_pruebas", _catalogos
    )

    response = await client.get("/sanidad/new")

    assert response.status_code == 200
    body = response.text
    assert 'name="csrf_token"' in body
    assert 'action="/sanidad"' in body
    # Catalogos_pruebas dropdown is populated.
    assert "Rabia" in body
    assert "Esterilización" in body


async def test_edit_actuacion_form_renders_with_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /sanidad/{id}/edit renders the prefilled form with csrf_token."""
    _login_as_key_user(client)
    actuacion = _actuacion()
    monkeypatch.setattr(
        sanidad_service,
        "get_actuacion_sanitaria_by_id",
        lambda _c, _id: actuacion,
    )

    def _catalogos(_client: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        sanidad_service, "list_catalogos_pruebas", _catalogos
    )

    response = await client.get("/sanidad/actu-123/edit")

    assert response.status_code == 200
    body = response.text
    assert 'name="csrf_token"' in body
    assert 'action="/sanidad/actu-123/update"' in body
    # Form is prefilled with the stored values.
    assert "animal-123" in body
    assert "2026-07-04" in body
    assert "Dra. Pérez" in body


# --- 4. Sad validation: fecha invalid -> 422 with Spanish message --------


async def test_create_actuacion_with_future_fecha_returns_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-24 regla 2 (fecha futura) renders 422 with a Spanish message."""
    from datetime import date, timedelta

    _login_as_key_user(client)

    def _catalogos(_client: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        sanidad_service, "list_catalogos_pruebas", _catalogos
    )

    future = (date.today() + timedelta(days=365)).isoformat()
    response = await make_csrf_request(
        client,
        "POST",
        "/sanidad",
        form_data={"animal_id": "animal-1", "fecha": future},
    )

    assert response.status_code == 422, (
        f"future fecha MUST be rejected with 422; got {response.status_code}"
    )
    body = response.text
    assert "fecha no puede ser futura" in body


async def test_create_actuacion_with_malformed_fecha_returns_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-24 regla 1 (formato) renders 422 with a Spanish message."""
    _login_as_key_user(client)

    def _catalogos(_client: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        sanidad_service, "list_catalogos_pruebas", _catalogos
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/sanidad",
        form_data={"animal_id": "animal-1", "fecha": "ayer"},
    )

    assert response.status_code == 422
    assert "fecha debe tener formato YYYY-MM-DD" in response.text


# --- 5. Happy path: create returns 303 to detail -------------------------


async def test_create_actuacion_success_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /sanidad with valid data returns 303 to /sanidad/{id}."""
    _login_as_key_user(client)
    actuacion = _actuacion()

    def _create(_client: Any, _params: dict[str, Any], **_: Any) -> Any:
        return actuacion

    def _catalogos(_client: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        sanidad_service, "create_actuacion_sanitaria", _create
    )
    monkeypatch.setattr(
        sanidad_service, "list_catalogos_pruebas", _catalogos
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/sanidad",
        form_data={"animal_id": "animal-1", "fecha": "2026-07-04"},
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/sanidad/actu-123"


# --- 6. 404 paths ---------------------------------------------------------


async def test_detail_returns_404_for_missing_id(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /sanidad/{missing} returns 404 when the row does not exist."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        sanidad_service,
        "get_actuacion_sanitaria_by_id",
        lambda _c, _id: None,
    )

    response = await client.get("/sanidad/missing-id")

    assert response.status_code == 404


async def test_delete_returns_404_for_missing_id(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /sanidad/{missing}/delete returns 404 when the row does not exist."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        sanidad_service,
        "delete_actuacion_sanitaria",
        lambda _c, _id, **__: False,
    )

    response = await make_csrf_request(
        client, "POST", "/sanidad/missing-id/delete"
    )

    assert response.status_code == 404


# --- 7. List with / without animal_id filter -----------------------------


async def test_list_actuaciones_without_filter_uses_global_list(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /sanidad (no query) calls list_actuaciones_sanitarias."""
    _login_as_key_user(client)

    def _list(_client: Any, *, animal_id: str | None = None) -> list[Any]:
        return [_actuacion()]

    monkeypatch.setattr(
        sanidad_service, "list_actuaciones_sanitarias", _list
    )

    response = await client.get("/sanidad")

    assert response.status_code == 200
    body = response.text
    assert "2026-07-04" in body
    assert "Dra. Pérez" in body


async def test_list_actuaciones_with_animal_id_uses_search(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /sanidad?animal_id=... delegates to search_actuaciones_by_animal."""
    _login_as_key_user(client)
    called_with: dict[str, Any] = {}

    def _search(_client: Any, animal_id: str) -> list[Any]:
        called_with["animal_id"] = animal_id
        return [_actuacion()]

    monkeypatch.setattr(
        sanidad_service, "search_actuaciones_by_animal", _search
    )

    response = await client.get("/sanidad?animal_id=animal-X")

    assert response.status_code == 200
    assert called_with == {"animal_id": "animal-X"}


# --- 8. No SQL en routes (layer boundary) --------------------------------


async def test_no_sql_executed_directly_from_routes(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All GET routes must run without direct SQL (service delegation only).

    The route_client spy raises AssertionError on any non-revalidation
    SQL — so the mere fact that this test completes (no exception) proves
    no route bypasses the service. We hit list + detail + new + edit,
    each routed through the service.
    """
    _login_as_key_user(client)

    # Stub the service functions so the routes can complete their renders.
    monkeypatch.setattr(
        sanidad_service,
        "list_actuaciones_sanitarias",
        lambda _c, **__: [_actuacion()],
    )
    monkeypatch.setattr(
        sanidad_service,
        "search_actuaciones_by_animal",
        lambda _c, _id: [_actuacion()],
    )
    monkeypatch.setattr(
        sanidad_service,
        "get_actuacion_sanitaria_by_id",
        lambda _c, _id: _actuacion(),
    )
    monkeypatch.setattr(
        sanidad_service,
        "list_catalogos_pruebas",
        lambda _c: [],
    )

    # Hit every GET endpoint. Each must complete without raising from the
    # spy. If a route bypassed the service and called client.execute_sql,
    # the spy would raise AssertionError.
    for path in (
        "/sanidad",
        "/sanidad?animal_id=animal-X",
        "/sanidad/new",
        "/sanidad/actu-123",
        "/sanidad/actu-123/edit",
    ):
        response = await client.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"


async def test_create_validation_error_survives_catalog_recovery_failure(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ValueError remains 422 even if catalog reload fails during recovery."""
    _login_as_key_user(client)

    def _create(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("fecha no puede ser futura")

    def _catalogos(_client: Any) -> list[dict[str, Any]]:
        raise InsForgeError(503, {"error": "catalog unavailable"})

    monkeypatch.setattr(
        sanidad_service, "create_actuacion_sanitaria", _create
    )
    monkeypatch.setattr(sanidad_service, "list_catalogos_pruebas", _catalogos)

    response = await make_csrf_request(
        client,
        "POST",
        "/sanidad",
        form_data={"animal_id": "animal-1", "fecha": "2030-01-01"},
    )

    assert response.status_code == 422
    assert "fecha no puede ser futura" in response.text


async def test_create_backend_error_returns_503_not_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """InsForgeError is logged and surfaced as backend outage, not validation."""
    _login_as_key_user(client)

    def _create(*args: Any, **kwargs: Any) -> Any:
        raise InsForgeError(503, {"error": "backend unavailable"})

    monkeypatch.setattr(
        sanidad_service, "create_actuacion_sanitaria", _create
    )
    monkeypatch.setattr(sanidad_service, "list_catalogos_pruebas", lambda _c: [])

    response = await make_csrf_request(
        client,
        "POST",
        "/sanidad",
        form_data={"animal_id": "animal-1", "fecha": "2026-07-04"},
    )

    assert response.status_code == 503
    assert "No se pudo contactar con el backend" in response.text


async def test_delete_backend_error_returns_503(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delete handles InsForgeError instead of leaking an unhandled 500."""
    _login_as_key_user(client)

    def _delete(*args: Any, **kwargs: Any) -> bool:
        raise InsForgeError(503, {"error": "backend unavailable"})

    monkeypatch.setattr(
        sanidad_service, "delete_actuacion_sanitaria", _delete
    )

    response = await make_csrf_request(
        client, "POST", "/sanidad/actu-123/delete"
    )

    assert response.status_code == 503
    assert "No se pudo contactar con el backend" in response.text
