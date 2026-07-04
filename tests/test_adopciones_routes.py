"""Route-layer tests for ADOPT-01 adopciones (CRUD).

Mirror of ``tests/test_entradas_routes.py`` and
``tests/test_foster_routes.py``: routes are pure HTTP / auth /
template glue. The fixture ``_NoSqlRouteClient`` enforces the
AGENTS.md layer-boundary rule (no ``client.execute_sql`` in routes).
All data access goes through ``app.modules.adopciones.service``.

Auth model (per #144): all 7 endpoints use ``require_authorized_user``,
so key_user / admin / developer can write. Reader is rejected by the
middleware-level auth guard (issue #143) before the handler runs.
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
from app.modules.adopciones import service as adopciones_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly.

    Mirrors the same pattern used in ``tests/test_entradas_routes.py``
    and ``tests/test_foster_routes.py``: routes own no SQL, they
    delegate to the service. If a route ever calls
    ``client.execute_sql``, the spy raises AssertionError and the
    failing test names the offending query.
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user`` (the lowest
        # authorized role that can still hit ``require_authorized_user``
        # POSTs per the adopciones design).
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
    """Mint a session cookie with a known CSRF token bound to it.

    The CSRF token here is what ``make_csrf_request`` echoes back via
    the ``X-CSRFToken`` header so the middleware passes the request.
    """
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-adopciones",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _adopcion() -> adopciones_service.Adopcion:
    """Canonical Adopcion fixture for assertions."""
    return adopciones_service.Adopcion(
        id="adop-123",
        animal_id="animal-123",
        voluntario_seguimiento_id="vol-123",
        fecha_adopcion="2026-07-04",
        fecha_devolucion=None,
        donativo_preadopcion=None,
        donativo_adopcion=None,
        nombre_adoptante="María García López",
        dni_adoptante="12345678A",
        telefono_adoptante="600123456",
        email_adoptante="maria@example.com",
        entrada_origen_id=None,
        observaciones="Adopción responsable",
        tipo_adopcion="regular",
    )


def _form_data() -> dict[str, str]:
    """Canonical form payload for create/update POSTs (all strings)."""
    return {
        "animal_id": "animal-123",
        "voluntario_seguimiento_id": "vol-123",
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": "",
        "donativo_preadopcion": "",
        "donativo_adopcion": "",
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": "",
        "observaciones": "Adopción responsable",
        "tipo_adopcion": "regular",
    }


# --- 1. Auth guards -------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/adopciones"),
        ("GET", "/adopciones/new"),
        ("POST", "/adopciones"),
        ("GET", "/adopciones/adop-123"),
        ("GET", "/adopciones/adop-123/edit"),
        ("POST", "/adopciones/adop-123/update"),
        ("POST", "/adopciones/adop-123/delete"),
    ],
)
async def test_adopciones_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every adopcion endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. GET /adopciones (list, happy path) -------------------------------


async def test_list_adopciones_delegates_to_service_and_renders_spanish_copy(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List endpoint delegates to the service and renders Spanish copy."""
    _login_as_key_user(client)
    calls: list[InsForgeClient] = []
    adopcion = _adopcion()

    def fake_list(service_client: InsForgeClient) -> list[adopciones_service.Adopcion]:
        calls.append(service_client)
        return [adopcion]

    monkeypatch.setattr(adopciones_service, "list_adopciones", fake_list)

    response = await client.get("/adopciones")

    assert response.status_code == 200
    assert calls == [route_client]
    body = response.text
    assert "Adopciones" in body
    assert "María García López" in body
    assert "Vigente" in body
    # Filter form for the adoptante query param is rendered.
    assert '<form method="get" action="/adopciones"' in body


# --- 3. GET /adopciones?adoptante=garcia (filter passthrough) -----------


async def test_list_adopciones_with_adoptante_query_param_uses_search(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``?adoptante=`` query param reaches search_adopciones_by_adoptante."""
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, str]] = []

    def fake_search(
        service_client: InsForgeClient, nombre_parcial: str
    ) -> list[adopciones_service.Adopcion]:
        calls.append((service_client, nombre_parcial))
        return [_adopcion()]

    monkeypatch.setattr(
        adopciones_service, "search_adopciones_by_adoptante", fake_search
    )

    response = await client.get("/adopciones", params={"adoptante": "garcia"})

    assert response.status_code == 200
    assert calls == [(route_client, "garcia")]
    assert "Filtrando por adoptante" in response.text


# --- 4. GET /adopciones/new (empty form) ---------------------------------


async def test_new_adopcion_form_renders_with_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """The ``/new`` form is rendered with a hidden CSRF input and the
    correct ``action="/adopciones"`` (create endpoint, not update)."""
    _login_as_key_user(client)

    response = await client.get("/adopciones/new")

    assert response.status_code == 200
    body = response.text
    assert "Nueva adopción" in body
    # PR-5B2: CSRF token field present (REQ-AH-7).
    assert 'name="csrf_token"' in body
    # Create endpoint, not the update endpoint.
    assert '<form method="post" action="/adopciones"' in body
    # Required-field asterisks signal the mandatory fields.
    assert "Nombre del adoptante" in body
    assert "Fecha de adopción" in body


# --- 5. POST /adopciones (create, happy path) -----------------------------


async def test_create_adopcion_valid_records_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid create form -> service returns the adopción -> 303 to detail."""
    _login_as_key_user(client)
    adopcion = _adopcion()
    calls: list[tuple[InsForgeClient, dict[str, Any]]] = []

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> adopciones_service.Adopcion:
        calls.append((service_client, params))
        return adopcion

    monkeypatch.setattr(adopciones_service, "create_adopcion", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones",
        form_data=_form_data(),
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/adopciones/adop-123"
    # The service received the dependency-injected client and the
    # operator's form payload.
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1]["nombre_adoptante"] == "María García López"
    assert calls[0][1]["tipo_adopcion"] == "regular"


# --- 6. POST /adopciones (create, sad path) ------------------------------


async def test_create_adopcion_sad_validation_rerenders_form_with_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service raises ``ValueError`` -> route re-renders the form with 422.

    Operator input is preserved so they can fix the failing field
    without retyping (mirror of the entradas and foster patterns).
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> adopciones_service.Adopcion:
        raise ValueError(
            "voluntario_seguimiento_id must reference an active volunteer"
        )

    monkeypatch.setattr(adopciones_service, "create_adopcion", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones",
        form_data=_form_data(),
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 422
    body = response.text
    assert "No se pudo guardar la adopción" in body
    assert (
        "voluntario_seguimiento_id must reference an active volunteer" in body
    )
    # Operator input is preserved (their nombre still in the body).
    assert 'value="María García López"' in body


# --- 7. GET /adopciones/{id} (detail, missing) ---------------------------


async def test_adopcion_detail_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail returns 404 when ``get_adopcion_by_id`` returns None."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        adopciones_service, "get_adopcion_by_id", lambda _c, _id: None
    )

    response = await client.get("/adopciones/missing-id")

    assert response.status_code == 404


# --- 8. GET /adopciones/{id} (detail, happy path) ------------------------


async def test_adopcion_detail_renders_data(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail renders the adopción's data plus the delete form with CSRF."""
    _login_as_key_user(client)
    adopcion = _adopcion()
    monkeypatch.setattr(
        adopciones_service, "get_adopcion_by_id", lambda _c, _id: adopcion
    )

    response = await client.get("/adopciones/adop-123")

    assert response.status_code == 200
    body = response.text
    assert "María García López" in body
    # Delete form is rendered with CSRF token.
    assert '<form method="post" action="/adopciones/adop-123/delete"' in body
    assert 'name="csrf_token"' in body
    # Edit link present.
    assert '/adopciones/adop-123/edit' in body
    # State badge "Vigente" because fecha_devolucion is None.
    assert "Vigente" in body


# --- 9. GET /adopciones/{id}/edit (edit form) ----------------------------


async def test_edit_adopcion_form_renders_with_csrf_and_action(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit form prefills from the adopción and posts to ``/update``."""
    _login_as_key_user(client)
    adopcion = _adopcion()
    monkeypatch.setattr(
        adopciones_service, "get_adopcion_by_id", lambda _c, _id: adopcion
    )

    response = await client.get("/adopciones/adop-123/edit")

    assert response.status_code == 200
    body = response.text
    assert "Editar adopción" in body
    # The CSRF defense-in-depth token field.
    assert 'name="csrf_token"' in body
    # Edit action, not the create action.
    assert '<form method="post" action="/adopciones/adop-123/update"' in body
    # Prefilled values from the adopción.
    assert 'value="María García López"' in body


# --- 10. POST /adopciones/{id}/update (update, happy path) --------------


async def test_update_adopcion_valid_records_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid update -> service returns the adopción -> 303 to detail page."""
    _login_as_key_user(client)
    adopcion = _adopcion()
    calls: list[tuple[InsForgeClient, str, dict[str, Any]]] = []

    def fake_update(
        service_client: InsForgeClient,
        adopcion_id: str,
        params: dict[str, Any],
    ) -> adopciones_service.Adopcion | None:
        calls.append((service_client, adopcion_id, params))
        return adopcion

    monkeypatch.setattr(adopciones_service, "update_adopcion", fake_update)

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones/adop-123/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/adopciones/adop-123"
    assert len(calls) == 1
    assert calls[0][1] == "adop-123"


async def test_update_adopcion_returns_404_when_row_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Update returns 404 when the service returns ``None`` (id missing)."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        adopciones_service, "update_adopcion", lambda _c, _id, _p: None
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones/missing/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 404


# --- 11. POST /adopciones/{id}/delete (delete, happy path) --------------


async def test_delete_adopcion_redirects_to_list(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soft-delete redirects to /adopciones when the service returns True."""
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, str]] = []

    def fake_delete(
        service_client: InsForgeClient, adopcion_id: str
    ) -> bool:
        calls.append((service_client, adopcion_id))
        return True

    monkeypatch.setattr(adopciones_service, "delete_adopcion", fake_delete)

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones/adop-123/delete",
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/adopciones"
    assert calls == [(route_client, "adop-123")]


async def test_delete_adopcion_returns_404_when_row_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delete returns 404 when the service returns False (id missing)."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        adopciones_service, "delete_adopcion", lambda _c, _id: False
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones/missing/delete",
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 404


# --- 12. Defense in depth: no client.execute_sql in routes source -------


def test_routes_source_has_no_client_execute_sql() -> None:
    """Static guard against the AGENTS.md §1 layer-boundary rule.

    The runtime ``_NoSqlRouteClient`` already enforces this for the
    tests that actually exercise the routes; this static check guards
    against the source being accidentally edited to call ``execute_sql``
    inline. Mirror of the foster / entradas pattern.
    """
    from pathlib import Path

    routes_path = Path(__file__).resolve().parents[1] / "app" / "modules" / "adopciones" / "routes.py"
    text = routes_path.read_text(encoding="utf-8")
    assert "client.execute_sql" not in text, (
        "routes.py must delegate SQL to adopciones_service; "
        "a direct client.execute_sql call violates AGENTS.md §1."
    )
