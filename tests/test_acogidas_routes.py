"""Route-layer tests for FOSTER-02 estancias de acogida.

Mirror of ``tests/test_foster_routes.py`` and ``tests/test_entradas_routes.py``:
routes are pure HTTP / auth / template glue. The fixture
``_NoSqlRouteClient`` enforces the AGENTS.md layer-boundary rule
(no ``client.execute_sql`` in routes). All data access goes through
``app.modules.acogidas.service``.

Coverage (15 atoms):

1.  Auth guard on every endpoint (parametrized over the 7 endpoints).
2.  ``GET /acogidas`` delegates to ``acogidas_service.list_acogidas``
    and renders the Spanish copy from ``acogidas/list.html``.
3.  ``GET /acogidas?activas_solo=1`` passes the filter through to the
    service.
4.  ``GET /acogidas/new`` renders the empty form with a CSRF token
    and ``form_action="/acogidas"``.
5.  ``POST /acogidas`` with valid records redirects to the detail
    page (303).
6.  ``POST /acogidas`` with a service validation error re-renders
    the form with 422 and preserves operator input.
7.  ``GET /acogidas/{id}`` returns 404 when the row is missing.
8.  ``GET /acogidas/{id}`` renders the detail view with the stay's
    data, computed duration, and active state.
9.  ``GET /acogidas/{id}/edit`` renders the form prefilled, with
    ``form_action="/acogidas/{id}/update"`` and a CSRF token.
10. ``POST /acogidas/{id}/update`` with valid records redirects to
    the detail page.
11. ``POST /acogidas/{id}/update`` returns 404 when the row is
    missing.
12. ``POST /acogidas/{id}/close`` closes the stay and redirects to
    detail (303).
13. ``POST /acogidas/{id}/close`` returns 404 when the row is
    missing.
14. ``POST /acogidas/{id}/delete`` soft-deletes and redirects to
    the list (303).
15. Route source contains no ``client.execute_sql`` call (defense
    in depth alongside the runtime ``_NoSqlRouteClient`` spy).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_insforge_client_dep
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.acogidas import service as acogidas_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly.

    Mirrors the same pattern used in
    ``tests/test_foster_routes.py`` and
    ``tests/test_entradas_routes.py``: routes own no SQL, they
    delegate to the service. If a route ever calls
    ``client.execute_sql``, the spy raises AssertionError and the
    failing test names the offending query.
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
        # Issue #143: require_authorized_user revalidates authorization per
        # request via the get_user_by_email service; that SELECT flows
        # through this client and is allowed. Any OTHER direct SQL from a
        # route handler still violates the "cero SQL en routes" contract.
        _reval = auth_reval_rows(query, params)
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
            "csrf_token": "test-csrf-token-acogidas",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _acogida() -> acogidas_service.Acogida:
    """Canonical Acogida fixture for assertions."""
    return acogidas_service.Acogida(
        id="acog-123",
        animal_id="11111111-1111-1111-1111-111111111111",
        casa_acogida_id="33333333-3333-3333-3333-333333333333",
        voluntario_acogida_id="vol-acog",
        voluntario_seguimiento1_id="vol-seg1",
        voluntario_seguimiento2_id=None,
        voluntario_sanitario_id="vol-san",
        fecha_inicio="2026-07-04",
        fecha_final=None,
        entrada_origen_id=None,
        direccion="Calle Mayor 12, Alcalá de Henares",
        telefono="600123456",
        observaciones="Animal tranquilo, sin medicación",
    )


def _form_data() -> dict[str, str]:
    """Canonical form payload for create/update POSTs."""
    return {
        "animal_id": "11111111-1111-1111-1111-111111111111",
        "casa_acogida_id": "33333333-3333-3333-3333-333333333333",
        "voluntario_acogida_id": "vol-acog",
        "voluntario_seguimiento1_id": "vol-seg1",
        "voluntario_seguimiento2_id": "",
        "voluntario_sanitario_id": "vol-san",
        "fecha_inicio": "2026-07-04",
        "fecha_final": "",
        "entrada_origen_id": "",
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
    }


# --- 1. Auth guards -------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/acogidas"),
        ("GET", "/acogidas/new"),
        ("POST", "/acogidas"),
        ("GET", "/acogidas/acog-123"),
        ("GET", "/acogidas/acog-123/edit"),
        ("POST", "/acogidas/acog-123/update"),
        ("POST", "/acogidas/acog-123/close"),
        ("POST", "/acogidas/acog-123/delete"),
    ],
)
async def test_acogidas_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every acogidas endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. GET /acogidas (list, happy path) ----------------------------------


async def test_list_acogidas_delegates_to_service_and_renders_spanish_copy(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List endpoint delegates to the service and renders Spanish copy."""
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, bool]] = []
    estancia = _acogida()

    def fake_list(
        service_client: InsForgeClient,
        activas_solo: bool = False,
    ) -> list[acogidas_service.Acogida]:
        calls.append((service_client, activas_solo))
        return [estancia]

    monkeypatch.setattr(acogidas_service, "list_acogidas", fake_list)

    response = await client.get("/acogidas")

    assert response.status_code == 200
    assert calls == [(route_client, False)]
    body = response.text
    assert "Estancias de acogida" in body
    assert "2026-07-04" in body
    # The list view exposes the filter for activas_solo.
    assert 'name="activas_solo"' in body or "activas_solo" in body


# --- 3. GET /acogidas?activas_solo=1 (filter passthrough) -----------------


async def test_list_acogidas_with_activas_solo_query_param(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``?activas_solo=1`` query param reaches the service unchanged."""
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, bool]] = []

    def fake_list(
        service_client: InsForgeClient,
        activas_solo: bool = False,
    ) -> list[acogidas_service.Acogida]:
        calls.append((service_client, activas_solo))
        return []

    monkeypatch.setattr(acogidas_service, "list_acogidas", fake_list)

    response = await client.get("/acogidas", params={"activas_solo": "1"})

    assert response.status_code == 200
    assert calls == [(route_client, True)]
    assert "Solo activas" in response.text or "activas_solo" in response.text


# --- 4. GET /acogidas/new (empty form) ------------------------------------


async def test_new_acogida_form_renders_with_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """The ``/new`` form is rendered with a hidden CSRF input and the
    correct ``action="/acogidas"`` (create endpoint, not update)."""
    _login_as_key_user(client)

    response = await client.get("/acogidas/new")

    assert response.status_code == 200
    body = response.text
    assert "Nueva estancia de acogida" in body
    # PR-5B2: CSRF token field present (REQ-AH-7).
    assert 'name="csrf_token"' in body
    # Create endpoint, not the update endpoint.
    assert '<form method="post" action="/acogidas"' in body
    # The required-field asterisks signal which fields are mandatory.
    assert "Animal" in body
    assert "Fecha de inicio" in body


# --- 5. POST /acogidas (create, happy path) -------------------------------


async def test_create_acogida_valid_records_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid create form -> service returns the estancia -> 303 to detail."""
    _login_as_key_user(client)
    estancia = _acogida()
    calls: list[tuple[InsForgeClient, dict[str, Any]]] = []

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> acogidas_service.Acogida:
        calls.append((service_client, params))
        return estancia

    monkeypatch.setattr(acogidas_service, "create_acogida", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas",
        form_data=_form_data(),
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/acogidas/acog-123"
    # The service received the dependency-injected client and the
    # operator's form payload.
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1]["animal_id"] == "11111111-1111-1111-1111-111111111111"


# --- 6. POST /acogidas (create, sad path) --------------------------------


async def test_create_acogida_sad_validation_rerenders_form_with_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service raises ``ValueError`` -> route re-renders the form with 422.

    Operator input is preserved so they can fix the failing field
    without retyping (mirror of the foster and entradas patterns).
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> acogidas_service.Acogida:
        raise ValueError("fecha_inicio es obligatorio y no puede estar vacio")

    monkeypatch.setattr(acogidas_service, "create_acogida", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas",
        form_data=_form_data(),
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 422
    body = response.text
    assert "No se pudo guardar la estancia de acogida" in body
    assert "fecha_inicio" in body
    # Operator input is preserved (their animal_id still in the body).
    assert 'value="11111111-1111-1111-1111-111111111111"' in body


# --- 7. GET /acogidas/{id} (detail, missing) -----------------------------


async def test_acogida_detail_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail returns 404 when ``get_acogida_by_id`` returns None."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        acogidas_service, "get_acogida_by_id", lambda _c, _id: None
    )

    response = await client.get("/acogidas/missing-id")

    assert response.status_code == 404


# --- 8. GET /acogidas/{id} (detail, happy path) --------------------------


async def test_acogida_detail_renders_data_duration_and_active_state(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail renders the stay's data + computed duration + active state.

    Uses an OPEN estancia so we can verify the close form is rendered
    (close form is only shown for active stays). The computed duration
    is None for open stays, so we exercise that path too.
    """
    _login_as_key_user(client)
    estancia = acogidas_service.Acogida(
        id="acog-active",
        animal_id="11111111-1111-1111-1111-111111111111",
        fecha_inicio="2026-07-04",
        fecha_final=None,
        activo=True,
    )
    monkeypatch.setattr(
        acogidas_service, "get_acogida_by_id", lambda _c, _id: estancia
    )

    response = await client.get("/acogidas/acog-active")

    assert response.status_code == 200
    body = response.text
    # fecha_inicio rendered.
    assert "2026-07-04" in body
    # Active state rendered.
    assert "Activa" in body
    # Open stay -> "Abierta" rendering for fecha_final + "sin duración cerrada".
    assert "Abierta" in body
    # Close + delete forms rendered with CSRF (close only on active stays).
    assert '<form method="post" action="/acogidas/acog-active/close"' in body
    assert '<form method="post" action="/acogidas/acog-active/delete"' in body
    assert 'name="csrf_token"' in body


# --- 9. GET /acogidas/{id}/edit (edit form) ------------------------------


async def test_edit_acogida_form_renders_with_csrf_and_action(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit form prefills from the estancia and posts to ``/update``.

    Verifies the edit path picks the right action so the form
    round-trips correctly.
    """
    _login_as_key_user(client)
    estancia = _acogida()
    monkeypatch.setattr(
        acogidas_service, "get_acogida_by_id", lambda _c, _id: estancia
    )

    response = await client.get("/acogidas/acog-123/edit")

    assert response.status_code == 200
    body = response.text
    assert "Editar estancia de acogida" in body
    # The CSRF defense-in-depth token field.
    assert 'name="csrf_token"' in body
    # Edit action, not the create action.
    assert '<form method="post" action="/acogidas/acog-123/update"' in body
    # Prefilled values from the estancia.
    assert 'value="11111111-1111-1111-1111-111111111111"' in body
    assert 'value="2026-07-04"' in body


# --- 10. POST /acogidas/{id}/update (update, happy path) ----------------


async def test_update_acogida_valid_records_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid update -> service returns the estancia -> 303 to detail page."""
    _login_as_key_user(client)
    estancia = _acogida()
    calls: list[tuple[InsForgeClient, str, dict[str, Any]]] = []

    def fake_update(
        service_client: InsForgeClient,
        acogida_id: str,
        params: dict[str, Any],
    ) -> acogidas_service.Acogida | None:
        calls.append((service_client, acogida_id, params))
        return estancia

    monkeypatch.setattr(acogidas_service, "update_acogida", fake_update)

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/acogidas/acog-123"
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1] == "acog-123"


# --- 11. POST /acogidas/{id}/update (404 when missing) ------------------


async def test_update_acogida_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``update_acogida`` returning ``None`` -> 404."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        acogidas_service, "update_acogida", lambda _c, _id, _p: None
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/missing/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 404


# --- 12. POST /acogidas/{id}/close (happy path) -------------------------


async def test_close_acogida_redirects_to_detail_when_successful(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close stay -> 303 redirect to detail page."""
    _login_as_key_user(client)
    estancia = _acogida()
    calls: list[tuple[InsForgeClient, str]] = []

    def fake_close(
        service_client: InsForgeClient, acogida_id: str
    ) -> acogidas_service.Acogida | None:
        calls.append((service_client, acogida_id))
        return estancia

    monkeypatch.setattr(acogidas_service, "close_acogida", fake_close)

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/close",
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/acogidas/acog-123"
    assert calls == [(route_client, "acog-123")]


# --- 13. POST /acogidas/{id}/close (404 when missing) --------------------


async def test_close_acogida_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``close_acogida`` returning ``None`` -> 404 (no redirect)."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        acogidas_service, "close_acogida", lambda _c, _id: None
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/missing/close",
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 404


# --- 14. POST /acogidas/{id}/delete (happy path + 404) -------------------


async def test_delete_acogida_redirects_to_list_when_successful(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soft-delete succeeds -> 303 redirect to the list page."""
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, str]] = []

    def fake_delete(service_client: InsForgeClient, acogida_id: str) -> bool:
        calls.append((service_client, acogida_id))
        return True

    monkeypatch.setattr(acogidas_service, "delete_acogida", fake_delete)

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/delete",
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/acogidas"
    assert calls == [(route_client, "acog-123")]


async def test_delete_acogida_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``delete_acogida`` returns False -> 404."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        acogidas_service, "delete_acogida", lambda _c, _id: False
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/missing/delete",
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 404


# --- 15. Defense in depth: route source has no ``.execute_sql`` ---------


def test_acogidas_route_source_contains_no_direct_execute_sql() -> None:
    """Static check: ``app/modules/acogidas/routes.py`` has no SQL.

    Defense in depth alongside the runtime ``_NoSqlRouteClient`` spy.
    If a future refactor accidentally re-introduces ``client.execute_sql``
    in the route module (the AGENTS.md §1 layer-boundary violation),
    this test fails before the runtime spy can catch it.
    """
    route_source = Path("app/modules/acogidas/routes.py")

    assert route_source.exists()
    assert ".execute_sql(" not in route_source.read_text(encoding="utf-8")
