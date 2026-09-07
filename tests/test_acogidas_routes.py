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

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_insforge_client_dep
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.acogidas import service as acogidas_service
from app.modules.animals.di.animals_di import get_animals_port
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
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user``; reader
        # rejection tests set this to ``reader`` so
        # ``require_writer_user`` produces 403 BEFORE any handler SQL.
        self.auth_reval_rol: str = "key_user"
        self.animals_port = object()

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
    app.dependency_overrides[get_animals_port] = lambda: spy.animals_port
    yield spy
    app.dependency_overrides.pop(get_insforge_client, None)
    app.dependency_overrides.pop(get_insforge_client_dep, None)
    app.dependency_overrides.pop(get_animals_port, None)


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


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Install a reader session; writer dep MUST reject with 403 (issue #144).

    The route client must have ``auth_reval_rol = "reader"`` BEFORE this
    helper runs so the per-request revalidation SELECT returns the same
    rol the cookie carries (otherwise ``require_authorized_user``'s cache
    could surface a stale rol from a previous test).
    """
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-acogidas",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _bypass_species_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """FOSTER-03 (#45): skip the new species gate in legacy-happy tests.

    FOSTER-03 closes the species gate bypass on POST/PATCH ``/acogidas``
    by routing every create/update through
    :func:`foster_assignment_service.evaluate_assignment` when the form
    carries a ``casa_acogida_id``. Existing tests that exercise the
    happy/sad paths of ``acogidas_service.create_acogida`` /
    ``update_acogida`` (the CRUD service itself) DO NOT care about the
    gate — they just want to confirm the route delegates and translates
    errors correctly. This helper monkeypatches ``evaluate_assignment``
    to a benign "admit" verdict so those tests keep passing without
    rewriting their assertions or fixtures.
    """
    from app.modules.foster import assignment as foster_assignment_service

    monkeypatch.setattr(
        foster_assignment_service,
        "evaluate_assignment",
        lambda _port, _c, _animal_id, _casa_id: foster_assignment_service.AssignmentDecision(
            decision="admit", reason=None, warnings=()
        ),
    )


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
    # FOSTER-03 (#45): skip the species gate; this test exercises the
    # CRUD service path, not the gate itself.
    _bypass_species_gate(monkeypatch)

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
    # FOSTER-03 (#45): skip the species gate; this test exercises the
    # CRUD service's ValueError path, not the gate.
    _bypass_species_gate(monkeypatch)

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


# --- Issue #139 P1 #4: TOCTOU FK violation translates to 422 (not 500) -----


async def test_create_acogida_route_translates_fk_violation_to_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service raises ``BackendError`` on concurrent FK violation -> 422.

    ``_validate_references`` runs SELECTs before the INSERT; a
    concurrent deactivate between the SELECT and the INSERT can still
    produce a PostgreSQL FK violation (PostgREST 400 with a
    ``"violates foreign key constraint"`` body). The service raises
    ``BackendError``; the route must translate it to 422 with the
    operator's form input preserved, NOT a 500.

    Mirrors the adopciones pattern: routes catch ``BackendError`` to
    surface 4xx-style backend failures as actionable 422s.
    """
    from app.core.data_access import BackendError

    _login_as_key_user(client)
    _bypass_species_gate(monkeypatch)

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> acogidas_service.Acogida:
        # Simulate a PostgreSQL FK violation arriving via PostgREST.
        raise BackendError(
            status_code=400,
            body={
                "code": "23503",
                "message": "insert or update on table 'acogidas' "
                "violates foreign key constraint "
                "'acogidas_animal_id_fkey'",
            },
        )

    monkeypatch.setattr(acogidas_service, "create_acogida", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas",
        form_data=_form_data(),
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 422, (
        f"FK violation MUST translate to 422 (not 500); got "
        f"{response.status_code}; body: {response.text!r}"
    )
    body = response.text
    # Spanish-friendly action message + entity label.
    assert "No se pudo guardar la estancia de acogida" in body
    assert "referencia extranjera" in body or "foreign key" in body.lower()
    # Operator input preserved.
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
    # FOSTER-03 (#45): skip the species gate; this test exercises the
    # CRUD service path, not the gate itself.
    _bypass_species_gate(monkeypatch)

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
    # FOSTER-03 (#45): skip the species gate so the test path reaches
    # the update service with the 404 sentinel intact.
    _bypass_species_gate(monkeypatch)
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


# ---------------------------------------------------------------------------
# Issue #144: a ``reader`` rol MUST be rejected by the 4 acogidas write
# routes (create / update / close / delete) with 403 BEFORE the handler
# runs. The no-SQL spy doubles as the assertion that nothing in the handler
# short-circuits past the writer dep.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        ("POST", "/acogidas", _form_data()),
        ("POST", "/acogidas/acog-123/update", _form_data()),
        ("POST", "/acogidas/acog-123/close", None),
        ("POST", "/acogidas/acog-123/delete", None),
    ],
    ids=["create", "update", "close", "delete"],
)
async def test_acogidas_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """Reader cannot POST on any acogidas write route (issue #144).

    The no-SQL spy (``_NoSqlRouteClient``) raises AssertionError on
    every non-revalidation query — a silent pass through the writer
    dep would crash the test loud and clear via the spy, in addition
    to the explicit 403 check.
    """
    route_client.auth_reval_rol = "reader"
    _login_as_reader(client)

    response = await make_csrf_request(
        client, method, path, form_data=form_data
    )

    assert response.status_code == 403, (
        f"reader {method} {path} MUST be 403; got {response.status_code}"
    )
    # Defense in depth: ensure the JSON error carries the writer
    # rejection message — if a future refactor swaps the dep and the
    # message drifts, the test catches it.
    assert "Permisos insuficientes" in response.text, (
        f"reader 403 response MUST carry 'Permisos insuficientes'; "
        f"got body: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# FOSTER-03 (#45): close the species gate bypass on POST/PATCH ``/acogidas``.
# Pre-#45, only ``/casas-acogida/{id}/asignar`` consulted the gate; a
# direct POST to ``/acogidas`` with a felino animal + canina-only casa
# slipped through. These three atoms pin the new behavior.
# ---------------------------------------------------------------------------


async def test_create_acogida_rejects_species_mismatch_when_casa_acogida_id_provided(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create with mismatching species → 422 + reason, no service INSERT.

    Patches :func:`foster_assignment_service.evaluate_assignment` to a
    ``block`` verdict and ``acogidas_service.create_acogida` with a
    sentinel that records every call. If the gate ever short-circuits,
    the service INSERT runs and the test fails loud.
    """
    from app.modules.foster import assignment as foster_assignment_service

    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_assignment_service,
        "evaluate_assignment",
        lambda _port, _c, _aid, _cid: foster_assignment_service.AssignmentDecision(
            decision="block",
            reason="la casa solo admite CANINA, no FELINA",
            warnings=(),
        ),
    )

    inserted: list[Any] = []
    monkeypatch.setattr(
        acogidas_service,
        "create_acogida",
        lambda *a, **kw: inserted.append((a, kw))
        or _acogida(),  # unreachable when gate works
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas",
        form_data=_form_data(),
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 422
    assert "CANINA" in response.text
    assert "FELINA" in response.text
    assert inserted == [], (
        "species gate MUST short-circuit BEFORE create_acogida runs; "
        f"captured: {inserted!r}"
    )


async def test_create_acogida_allows_legacy_no_casa_acogida_id(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create without casa_acogida_id skips the gate (FOSTER-02 compat).

    Legacy FOSTER-02 estancias without a casa MUST keep working:
    ``_enforce_species_gate`` returns ``None`` when ``casa_acogida_id``
    is falsy, so the create flow proceeds straight to the service. The
    test patches :func:`evaluate_assignment` with a sentinel that would
    block; if it ever runs, the test fails loud.
    """
    from app.modules.foster import assignment as foster_assignment_service

    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_assignment_service,
        "evaluate_assignment",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError(
                "gate MUST NOT run when casa_acogida_id is empty (legacy compat)"
            )
        ),
    )

    estancia = _acogida()
    calls: list[Any] = []

    def fake_create(_c, _p):
        calls.append(_p)
        return estancia

    monkeypatch.setattr(acogidas_service, "create_acogida", fake_create)

    form = _form_data()
    form["casa_acogida_id"] = ""  # legacy compat path
    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas",
        form_data=form,
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/acogidas/acog-123"
    assert len(calls) == 1
    assert calls[0]["casa_acogida_id"] is None


async def test_update_acogida_rejects_species_mismatch_when_casa_acogida_id_provided(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update with mismatching species → 422 + reason, no service UPDATE.

    The update path mirrors create: gate runs first, returns 422 on
    ``block`` verdict, the service ``update_acogida`` sentinel records
    any call. If the gate short-circuits, the test fails loud.
    """
    from app.modules.foster import assignment as foster_assignment_service

    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_assignment_service,
        "evaluate_assignment",
        lambda _port, _c, _aid, _cid: foster_assignment_service.AssignmentDecision(
            decision="block",
            reason="la casa solo admite CANINA, no FELINA",
            warnings=(),
        ),
    )

    updated: list[Any] = []
    monkeypatch.setattr(
        acogidas_service,
        "update_acogida",
        lambda *a, **kw: updated.append((a, kw))
        or _acogida(),  # unreachable when gate works
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-acogidas",
    )

    assert response.status_code == 422
    assert "CANINA" in response.text
    assert "FELINA" in response.text
    assert updated == [], (
        "species gate MUST short-circuit BEFORE update_acogida runs; "
        f"captured: {updated!r}"
    )


# ---------------------------------------------------------------------------
# Issue #141: P0 silent-data-loss on ``fecha_final``. The form rendered
# the field, FastAPI parsed it, and the route forwarded it — but the
# service silently dropped it (column was not in ``_WRITE_COLUMNS``).
#
# The two atoms below go POST -> route -> REAL service
# (``create_acogida`` / ``update_acogida``), not a monkeypatched
# service. A real ``InsForgeClient`` backed by ``httpx.MockTransport``
# is injected via ``app.dependency_overrides``; the captured SQL is
# the proof that fecha_final reaches the INSERT/UPDATE placeholders.
# ---------------------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _feed_handler(
    insert_row: dict[str, Any] | None = None,
    update_row: dict[str, Any] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """Build an httpx mock handler that lets create/update through.

    Mirrors ``tests/test_acogidas.py::_make_handler`` — except here
    we feed real InsForge envelopes (route also calls
    ``auth_reval_rows`` via the per-request revalidation, which we
    route through ``auth_reval_rows`` from conftest).
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        # Per-request auth revalidation: SELECT from usuarios_autorizados
        if "FROM usuarios_autorizados" in body["query"]:
            return _json_response(
                200,
                [
                    {
                        "email": "ana@example.com",
                        "rol": "key_user",
                        "is_authorized": True,
                        "activo": True,
                    }
                ],
            )
        # Generic FK existence check: SELECT id, activo FROM <table>.
        # Covers animales / casas_acogida / voluntarios (all active by
        # construction; this test only exercises the fecha_final path).
        if body["query"].lstrip().startswith("SELECT id, activo FROM"):
            return _json_response(
                200,
                [{"id": body["params"][0], "activo": True}],
            )
        # The actual INSERT into acogidas.
        if "INSERT INTO acogidas" in body["query"]:
            return _json_response(200, [insert_row or _acogida_row()])
        # The actual UPDATE on acogidas (dynamic SET clause post-fix).
        if "UPDATE acogidas SET" in body["query"]:
            return _json_response(200, [update_row or _acogida_row()])
        # LIFECYCLE-02 (issue #32): create_acogida / close_acogida fire
        # ``record_event`` + ``close_previous_situation`` writes and
        # refresh ``animal_current_state`` via
        # ``actualizar_estado_animal``. Those writes hit:
        #   * ``INSERT INTO animal_lifecycle_events`` (event log)
        #   * ``FROM entradas/acogidas/adopciones`` active-collection
        #     SELECTs (the cascade inputs)
        #   * ``LEFT JOIN animal_current_state`` (ficha SELECT)
        #   * ``INSERT INTO animal_current_state`` (cache UPSERT)
        # Returning an empty list keeps the cascade happy ("no other
        # active placements") without coupling the route test to the
        # lifecycle SQL shape -- that's pinned by
        # ``tests/test_acogidas_lifecycle_events.py``.
        if "INSERT INTO animal_lifecycle_events" in body["query"]:
            return _json_response(200, [])
        if "INSERT INTO animal_current_state" in body["query"]:
            return _json_response(200, [])
        if (
            "FROM entradas" in body["query"]
            and "fecha_salida IS NULL" in body["query"]
            and "activo = true" in body["query"]
        ):
            return _json_response(200, [])
        if (
            "FROM acogidas" in body["query"]
            and "fecha_final IS NULL" in body["query"]
            and "activo = true" in body["query"]
        ):
            return _json_response(200, [])
        if (
            "FROM adopciones" in body["query"]
            and "fecha_devolucion IS NULL" in body["query"]
            and "activo = true" in body["query"]
        ):
            return _json_response(200, [])
        if (
            "LEFT JOIN animal_current_state" in body["query"]
            and "FROM animales" in body["query"]
        ):
            return _json_response(200, [_acogida_row()])
        raise AssertionError(f"Unexpected SQL: {body['query']!r}")

    return _handler


def _acogida_row() -> dict[str, Any]:
    """Canonical returned row for the mock — matches Acogida dataclass."""
    return {
        "id": "acog-123",
        "animal_id": "11111111-1111-1111-1111-111111111111",
        "casa_acogida_id": "33333333-3333-3333-3333-333333333333",
        "voluntario_acogida_id": "vol-acog",
        "voluntario_seguimiento1_id": "vol-seg1",
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": "vol-san",
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "fecha_baja": None,
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }


def _install_feed_client(
    captured: list[dict[str, Any]],
    insert_row: dict[str, Any] | None = None,
    update_row: dict[str, Any] | None = None,
) -> InsForgeClient:
    """Inject an httpx.MockTransport-backed real InsForgeClient.

    Returns the client so callers can ``.close()`` after the test.
    The dependency override lets the real service code path run
    against the mock transport — no monkeypatching of the service
    itself, which is what makes this a true end-to-end atom.
    """

    def _recording(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return _feed_handler(insert_row=insert_row, update_row=update_row)(request)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording),
    )
    app.dependency_overrides[get_insforge_client] = lambda: client
    app.dependency_overrides[get_insforge_client_dep] = lambda: client
    app.dependency_overrides[get_animals_port] = object
    return client


async def test_post_create_with_fecha_final_persists(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /acogidas with fecha_final reaches the service's INSERT.

    End-to-end: form -> route -> real create_acogida -> INSERT INTO
    acogidas. The captured INSERT params MUST carry the date; before
    the fix the column was absent from ``_WRITE_COLUMNS`` so the
    param was never built.
    """
    _login_as_key_user(client)
    # Bypass the FOSTER-03 species gate; this test is about fecha_final
    # persistence, not gate semantics.
    _bypass_species_gate(monkeypatch)
    captured: list[dict[str, Any]] = []
    feed_client = _install_feed_client(
        captured,
        insert_row=_acogida_row(),
    )

    form = _form_data()
    form["fecha_final"] = "2026-07-15"

    try:
        response = await make_csrf_request(
            client,
            "POST",
            "/acogidas",
            form_data=form,
            csrf_token="test-csrf-token-acogidas",
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/acogidas/acog-123"
    finally:
        feed_client.close()
        app.dependency_overrides.pop(get_insforge_client, None)
        app.dependency_overrides.pop(get_insforge_client_dep, None)
        app.dependency_overrides.pop(get_animals_port, None)

    insert_call = next(c for c in captured if "INSERT INTO acogidas" in c["query"])
    # fecha_final MUST reach the INSERT params list verbatim.
    assert "2026-07-15" in insert_call["params"], (
        f"fecha_final was silently dropped on route -> service -> SQL "
        f"chain. captured INSERT params: {insert_call['params']!r}"
    )


async def test_post_update_reopens_when_fecha_final_empty(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /acogidas/{id}/update with fecha_final=\"\" -> UPDATE sets NULL.

    End-to-end reopen. The HTML date input clears to ``""`` when the
    operator deletes the value; the route normalizes that to ``None``
    and the service writes NULL to fecha_final (closing-state ->
    open).
    """
    _login_as_key_user(client)
    _bypass_species_gate(monkeypatch)
    captured: list[dict[str, Any]] = []
    # Row returned by the mock has fecha_final=None (the reopen outcome).
    reopened_row = _acogida_row()
    reopened_row["fecha_final"] = None
    feed_client = _install_feed_client(
        captured, update_row=reopened_row
    )

    form = _form_data()
    form["fecha_final"] = ""  # operator clears the closure date

    try:
        response = await make_csrf_request(
            client,
            "POST",
            "/acogidas/acog-123/update",
            form_data=form,
            csrf_token="test-csrf-token-acogidas",
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/acogidas/acog-123"
    finally:
        feed_client.close()
        app.dependency_overrides.pop(get_insforge_client, None)
        app.dependency_overrides.pop(get_insforge_client_dep, None)
        app.dependency_overrides.pop(get_animals_port, None)

    update_call = next(c for c in captured if "UPDATE acogidas SET" in c["query"])
    # The UPDATE must include fecha_final in its SET clause (because
    # the form sent an empty value) and must pass None (NOT the empty
    # string, which PostgreSQL would reject on a ``date`` column).
    assert "fecha_final" in update_call["query"], (
        f"UPDATE must include fecha_final when the form sends an empty "
        f"value (reopen). Got SQL: {update_call['query']!r}"
    )
    # Position the fecha_final param in the UPDATE parameter list. After
    # the fix fecha_final is one of the SET columns, whose position
    # depends on which columns are present in the params. We use the
    # service's _WRITE_COLUMNS (project's source of truth) to compute
    # the positional index, then add 2 because $1 is the id.
    assert "fecha_final" in acogidas_service._WRITE_COLUMNS, (
        f"service._WRITE_COLUMNS must include 'fecha_final' so the "
        f"UPDATE can persist reopen semantics. Got: "
        f"{acogidas_service._WRITE_COLUMNS!r}"
    )
    fecha_final_position = (
        acogidas_service._WRITE_COLUMNS.index("fecha_final") + 2
    )
    assert update_call["params"][fecha_final_position] is None, (
        f"route must send None (not the empty string) for fecha_final "
        f"when the operator clears the field. "
        f"Param at position {fecha_final_position}: "
        f"{update_call['params'][fecha_final_position]!r}. "
        f"Full params: {update_call['params']!r}"
    )
