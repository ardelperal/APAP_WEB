"""Route-layer tests for FOSTER-01 casas de acogida.

Mirror of ``tests/test_entradas_routes.py`` and
``tests/test_entradas_batch_routes.py``: routes are pure HTTP / auth /
template glue. The fixture ``_NoSqlRouteClient`` enforces the
AGENTS.md layer-boundary rule (no ``client.execute_sql`` in routes).
All data access goes through ``app.modules.foster.service``.

Coverage (16 atoms):

1. Auth guard on every endpoint (parametrized over the 7 endpoints).
2. ``GET /casas-acogida`` delegates to ``foster_service.list_casas_acogida``
   and renders the Spanish copy from ``casas_acogida/list.html``.
3. ``GET /casas-acogida?especie=FELINA`` passes the filter through to the
   service.
4. ``GET /casas-acogida/new`` renders the empty form with a CSRF token
   and ``form_action="/casas-acogida"``.
5. ``POST /casas-acogida`` with valid records redirects to the detail
   page (303).
6. ``POST /casas-acogida`` with a service validation error re-renders
   the form with 422 and preserves operator input.
7. ``GET /casas-acogida/{id}`` returns 404 when the row is missing.
8. ``GET /casas-acogida/{id}`` renders the detail view with the casa's
   data.
9. ``GET /casas-acogida/{id}/edit`` renders the form prefilled, with
    ``form_action="/casas-acogida/{id}/update"`` and a CSRF token.
10. ``POST /casas-acogida/{id}/update`` with valid records redirects to
    the detail page.
11. ``POST /casas-acogida/{id}/update`` with a validation error
    re-renders the form with 422.
12. ``POST /casas-acogida/{id}/update`` returns 404 when the row is
    missing.
13. ``POST /casas-acogida/{id}/delete`` soft-deletes and redirects to
    the list (303) when the service returns True.
14. ``POST /casas-acogida/{id}/delete`` returns 404 when the service
    returns False (row missing or already inactive).
15. Route source contains no ``client.execute_sql`` call (defense in
    depth alongside the runtime ``_NoSqlRouteClient`` spy).
16. ``POST /casas-acogida`` with ``capacidad=""`` yields Pydantic's
    standard JSON 422 (Refs #140 W2 follow-up to PR #162): the empty
    string is rejected at parse time, the service is never reached,
    and the response is JSON with ``detail[].loc == ["body",
    "capacidad"]`` — NOT the service-level HTML re-render.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_insforge_client_dep
from app.core.config import get_settings
from app.core.data_access import SqlExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.foster import service as foster_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(SqlExecutor):
    """Client spy that fails if a route executes SQL directly.

    Mirrors the same pattern used in
    ``tests/test_entradas_routes.py`` and
    ``tests/test_entradas_batch_routes.py``: routes own no SQL, they
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
            "csrf_token": "test-csrf-token-foster",
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
            "csrf_token": "test-csrf-token-foster",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_developer(client: httpx.AsyncClient) -> None:
    """FOSTER-03 (#45): developer session for the overrides-dev-only paths.

    Same pattern as :func:`_login_as_key_user` but with ``rol="developer"``.
    The route client's ``auth_reval_rol`` MUST be flipped to ``"developer"``
    BEFORE this helper runs so the per-request revalidation SELECT echoes
    the cookie's rol (otherwise :func:`require_authorized_user`'s cache
    could surface a stale rol from a previous test).
    """
    token = write_session(
        {
            "email": "dev@example.com",
            "rol": "developer",
            "user_id": "u-dev",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-foster",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _casa() -> foster_service.CasaAcogida:
    """Canonical CasaAcogida fixture for assertions."""
    return foster_service.CasaAcogida(
        id="casa-123",
        nombre="María",
        apellidos="García",
        dni_acogedor="12345678A",
        calle="Calle Mayor",
        numero="12",
        piso="3",
        letra="A",
        localidad="Alcalá de Henares",
        provincia="Madrid",
        cp="28801",
        telefono="600123456",
        telefono2=None,
        email="maria@example.com",
        vinculacion="Socia",
        caracteristicas="Piso con patio",
        coche="Sí",
        especie_preferente="CANINA",
        observaciones=None,
        capacidad=3,
    )


def _form_data() -> dict[str, str]:
    """Canonical form payload for create/update POSTs.

    All string values so they survive httpx form-encoded transport.
    Note ``capacidad`` is a string here: ``_form_data_to_params``
    in the route converts it to int; sending "3" exercises the real
    form path rather than a Python-bypass.
    """
    return {
        "nombre": "María",
        "apellidos": "García",
        "dni_acogedor": "12345678A",
        "calle": "Calle Mayor",
        "numero": "12",
        "piso": "3",
        "letra": "A",
        "localidad": "Alcalá de Henares",
        "provincia": "Madrid",
        "cp": "28801",
        "telefono": "600123456",
        "telefono2": "",
        "email": "maria@example.com",
        "vinculacion": "Socia",
        "caracteristicas": "Piso con patio",
        "coche": "Sí",
        "especie_preferente": "CANINA",
        "observaciones": "",
        "capacidad": "3",
    }


# --- 1. Auth guards -------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/casas-acogida"),
        ("GET", "/casas-acogida/new"),
        ("POST", "/casas-acogida"),
        ("GET", "/casas-acogida/casa-123"),
        ("GET", "/casas-acogida/casa-123/edit"),
        ("POST", "/casas-acogida/casa-123/update"),
        ("POST", "/casas-acogida/casa-123/delete"),
    ],
)
async def test_foster_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every foster endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. GET /casas-acogida (list, happy path) -----------------------------


async def test_list_casas_acogida_delegates_to_service_and_renders_spanish_copy(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List endpoint delegates to the service and renders Spanish copy.

    Verifies three properties at once:

    - The route calls ``foster_service.list_casas_acogida(client)``
      exactly once, passing the dependency-injected client.
    - The list HTML renders the casa's primary fields (the Spanish
      copy ``María García``, ``CANINA``, ``3``).
    - The CSRF filter form (``<form method="get" action="/casas-acogida"``)
      is in the body so operators can apply the especie filter.
    """
    _login_as_key_user(client)
    calls: list[SqlExecutor] = []
    casa = _casa()

    def fake_list(
        service_client: SqlExecutor, especie: str | None = None
    ) -> list[foster_service.CasaAcogida]:
        calls.append(service_client)
        return [casa]

    monkeypatch.setattr(foster_service, "list_casas_acogida", fake_list)

    response = await client.get("/casas-acogida")

    assert response.status_code == 200
    assert calls == [route_client]
    body = response.text
    assert "Casas de acogida" in body
    assert "María García" in body
    assert "CANINA" in body
    # capacidad renders in the row.
    assert "3</td>" in body or ">3<" in body
    # The list view exposes the filter form for the especie query param.
    assert '<form method="get" action="/casas-acogida"' in body


# --- 3. GET /casas-acogida?especie=FELINA (filter passthrough) -----------


async def test_list_casas_acogida_with_especie_query_param(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``?especie=`` query param reaches the service unchanged."""
    _login_as_key_user(client)
    calls: list[tuple[SqlExecutor, str | None]] = []

    def fake_list(
        service_client: SqlExecutor, especie: str | None = None
    ) -> list[foster_service.CasaAcogida]:
        calls.append((service_client, especie))
        return []

    monkeypatch.setattr(foster_service, "list_casas_acogida", fake_list)

    response = await client.get("/casas-acogida", params={"especie": "FELINA"})

    assert response.status_code == 200
    assert calls == [(route_client, "FELINA")]
    assert "Filtrando por especie preferente" in response.text


# --- 4. GET /casas-acogida/new (empty form) ------------------------------


async def test_new_casa_acogida_form_renders_with_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """The ``/new`` form is rendered with a hidden CSRF input and the
    correct ``action="/casas-acogida"`` (create endpoint, not update)."""
    _login_as_key_user(client)

    response = await client.get("/casas-acogida/new")

    assert response.status_code == 200
    body = response.text
    assert "Nueva casa de acogida" in body
    # PR-5B2: CSRF token field present (REQ-AH-7).
    assert 'name="csrf_token"' in body
    # Create endpoint, not the update endpoint.
    assert '<form method="post" action="/casas-acogida"' in body
    # The required-field asterisks signal which fields are mandatory.
    assert "Nombre" in body
    assert "Capacidad" in body


# --- 5. POST /casas-acogida (create, happy path) --------------------------


async def test_create_casa_acogida_valid_records_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid create form -> service returns the casa -> 303 to detail."""
    _login_as_key_user(client)
    casa = _casa()
    calls: list[tuple[SqlExecutor, dict[str, Any]]] = []

    def fake_create(
        service_client: SqlExecutor, params: dict[str, Any]
    ) -> foster_service.CasaAcogida:
        calls.append((service_client, params))
        return casa

    monkeypatch.setattr(foster_service, "create_casa_acogida", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida",
        form_data=_form_data(),
        csrf_token="test-csrf-token-foster",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/casas-acogida/casa-123"
    # The service received the dependency-injected client and the
    # operator's form payload (after _form_data_to_params int coercion).
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1]["nombre"] == "María"
    assert calls[0][1]["capacidad"] == 3  # _form_data_to_params coerced "3"


# --- 6. POST /casas-acogida (create, sad path) ----------------------------


async def test_create_casa_acogida_sad_validation_rerenders_form_with_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service raises ``ValueError`` -> route re-renders the form with 422.

    Operator input is preserved so they can fix the failing field
    without retyping (mirror of the entradas and entradas_batch
    patterns).
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: SqlExecutor, params: dict[str, Any]
    ) -> foster_service.CasaAcogida:
        raise ValueError("capacidad debe ser un entero positivo (>= 1)")

    monkeypatch.setattr(foster_service, "create_casa_acogida", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida",
        form_data=_form_data(),
        csrf_token="test-csrf-token-foster",
    )

    assert response.status_code == 422
    body = response.text
    assert "No se pudo guardar la casa de acogida" in body
    assert "capacidad debe ser un entero positivo" in body
    # Operator input is preserved (their nombre still in the body).
    assert 'value="María"' in body


# ---------------------------------------------------------------------------
# Refs #140 W2 follow-up (PR #162 retro review): empty ``capacidad`` must
# yield Pydantic's standard JSON 422, NOT the service-level Spanish render
# exercised above. The W2 subagent moved ``capacidad`` validation from a
# silent ``try/except int(...)`` in the route to Pydantic's int coercion at
# parse time. This atom pins the new contract.
# ---------------------------------------------------------------------------


async def test_post_casa_acogida_with_empty_capacidad_returns_pydantic_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refs #140 W2 follow-up: empty ``capacidad`` -> Pydantic JSON 422.

    Regression guard for the W2 behavior change landed in PR #162
    (commit eb76e19). Before that PR, ``create_casa_acogida_view``
    parsed ``capacidad`` via a silent ``try/except int(capacidad_raw)``
    in the route: on ``ValueError`` the empty string was passed
    through to the service, which then re-raised a Spanish
    ``ValueError(...)`` and the route re-rendered the form with
    HTTP 422 + the operator's input preserved.

    After PR #162, ``CasaAcogidaForm.capacidad`` is typed as ``int``
    (Pydantic v2 ``BaseModel`` + ``Form(...)``), so FastAPI's
    ``RequestValidationError`` path catches the empty string at parse
    time and returns the standard JSON 422 with ``detail[].loc`` ==
    ``["body", "capacidad"]`` and a ``type: int_parsing`` marker. The
    service is never reached.

    This atom pins the new contract: status 422 from the ROUTE (not
    from the service), JSON body carrying ``capacidad`` and the
    integer-parsing message. If a future refactor re-introduces the
    silent try/except or relaxes ``capacidad`` back to ``str``, the
    service mock raises AssertionError AND the JSON shape check fails
    loudly.

    Note on transport: httpx 0.28+ preserves empty-string form
    values in the URL-encoded body (``capacidad=``), so
    ``form_data={"capacidad": ""}`` does reach the handler. The
    parser-side field-required path is therefore NOT exercised by
    this test - the field IS present, just empty; Pydantic rejects
    the empty string at int coercion. A separate regression test
    for an OMITTED ``capacidad`` is intentionally absent because
    that path was never part of the W2 bug.
    """
    _login_as_key_user(client)

    # Sentinel: the service MUST NOT be reached when Pydantic catches
    # the empty string at parse time. If anything short-circuits the
    # parse-error path (a future relax of ``capacidad`` back to
    # ``str``, a missing form-definition, etc.), the AssertionError
    # names the regression loud and clear.
    def _create_must_not_be_called(
        service_client: SqlExecutor, params: dict[str, Any]
    ) -> foster_service.CasaAcogida:
        raise AssertionError(
            "Pydantic parse should reject empty 'capacidad' BEFORE "
            f"the service is called; got params={params!r}"
        )

    monkeypatch.setattr(
        foster_service, "create_casa_acogida", _create_must_not_be_called
    )

    payload = _form_data()
    payload["capacidad"] = ""  # empty string (NOT omitted) - the W2 case

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida",
        form_data=payload,
        csrf_token="test-csrf-token-foster",
    )

    # FastAPI's RequestValidationError -> HTTP 422.
    assert response.status_code == 422, (
        f"empty capacidad MUST trigger Pydantic 422 (refs #140 W2); "
        f"got status={response.status_code} body={response.text!r}"
    )
    # JSON body, NOT the Spanish HTML re-render the service-level
    # path would produce. Pinning the content-type protects against a
    # future change that wraps the parse error in an HTML page.
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type, (
        f"Pydantic 422 MUST come back as JSON; got content-type={content_type!r}"
    )
    body = response.text
    # Pydantic v2 standard ``detail`` array - the failing field name
    # appears as ``"body","capacidad"`` in ``loc``. Lowercased so the
    # assertion survives JSON-quote or field-name case variations.
    assert "capacidad" in body, (
        f"422 body MUST name 'capacidad' as the failing field; got: {body!r}"
    )
    # Pydantic v2 standard messages for ``int`` parse failures carry
    # one of: ``"Input should be a valid integer"``, ``"int_parsing"``,
    # or a localized variant. Match on the stable substrings.
    assert (
        "integer" in body.lower() or "int_parsing" in body.lower()
    ), f"422 body MUST mention integer parsing; got: {body!r}"


# --- 7. GET /casas-acogida/{id} (detail, missing) ------------------------


async def test_casa_acogida_detail_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail returns 404 when ``get_casa_acogida_by_id`` returns None."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: None
    )

    response = await client.get("/casas-acogida/missing-id")

    assert response.status_code == 404


# --- 8. GET /casas-acogida/{id} (detail, happy path) ---------------------


async def test_casa_acogida_detail_renders_data(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail renders the casa's data plus the delete form with CSRF.

    FOSTER-03 (#45): the detail view now also looks up the active
    stay count and the top 10 capacity overrides via the assignment
    service. Both helpers are monkeypatched to fixed values so the
    SQL-spy ``_NoSqlRouteClient`` stays clean (the route still
    delegates to the service, never to ``execute_sql`` directly).
    """
    from app.modules.foster import assignment as assignment_service

    _login_as_key_user(client)
    casa = _casa()
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: casa
    )
    monkeypatch.setattr(
        assignment_service,
        "count_active_estancias_for_casa",
        lambda _c, _id: 0,
    )
    monkeypatch.setattr(
        assignment_service,
        "list_overrides_for_casa",
        lambda _c, _id: [],
    )

    response = await client.get("/casas-acogida/casa-123")

    assert response.status_code == 200
    body = response.text
    assert "María García" in body
    assert "Calle Mayor" in body
    # Coche with tilde preserved through the render (P1 fidelity).
    assert "Sí" in body
    # Delete form is rendered with CSRF token.
    assert '<form method="post" action="/casas-acogida/casa-123/delete"' in body
    assert 'name="csrf_token"' in body
    # Edit link present.
    assert '/casas-acogida/casa-123/edit' in body
    # FOSTER-03: assign link present.
    assert '/casas-acogida/casa-123/asignar' in body
    # FOSTER-03: estancias activas badge visible.
    assert "Estancias activas" in body


# --- 9. GET /casas-acogida/{id}/edit (edit form) -------------------------


async def test_edit_casa_acogida_form_renders_with_csrf_and_action(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit form prefills from the casa and posts to ``/update``.

    The form action is context-dependent: ``/casas-acogida/{id}/update``
    for edit, ``/casas-acogida`` for new. Verifies the edit path picks
    the right one so the form round-trips correctly.
    """
    _login_as_key_user(client)
    casa = _casa()
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: casa
    )

    response = await client.get("/casas-acogida/casa-123/edit")

    assert response.status_code == 200
    body = response.text
    assert "Editar casa de acogida" in body
    # The CSRF defense-in-depth token field.
    assert 'name="csrf_token"' in body
    # Edit action, not the create action.
    assert '<form method="post" action="/casas-acogida/casa-123/update"' in body
    # Prefilled values from the casa.
    assert 'value="María"' in body
    assert 'value="García"' in body
    assert 'value="Calle Mayor"' in body
    # coche "Sí" selected in the option list.
    assert '<option value="Sí" selected' in body


# --- 10. POST /casas-acogida/{id}/update (update, happy path) ------------


async def test_update_casa_acogida_valid_records_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid update -> service returns the casa -> 303 to detail page."""
    _login_as_key_user(client)
    casa = _casa()
    calls: list[tuple[SqlExecutor, str, dict[str, Any]]] = []

    def fake_update(
        service_client: SqlExecutor,
        casa_id: str,
        params: dict[str, Any],
    ) -> foster_service.CasaAcogida | None:
        calls.append((service_client, casa_id, params))
        return casa

    monkeypatch.setattr(foster_service, "update_casa_acogida", fake_update)

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-foster",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/casas-acogida/casa-123"
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1] == "casa-123"
    assert calls[0][2]["nombre"] == "María"


# --- 11. POST /casas-acogida/{id}/update (update, sad path) --------------


async def test_update_casa_acogida_sad_validation_rerenders_form_with_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service raises ValueError on update -> form re-renders with 422.

    Mirrors the create sad-path: operator input is preserved and the
    error message is surfaced in the same banner so they can fix
    without retyping.
    """
    _login_as_key_user(client)

    def fake_update(
        service_client: SqlExecutor,
        casa_id: str,
        params: dict[str, Any],
    ) -> foster_service.CasaAcogida | None:
        raise ValueError("coche debe ser 'Sí' o 'No' (con tilde en la primera opcion)")

    monkeypatch.setattr(foster_service, "update_casa_acogida", fake_update)

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-foster",
    )

    assert response.status_code == 422
    body = response.text
    assert "No se pudo guardar la casa de acogida" in body
    assert "coche debe ser" in body
    # Edit action preserved (not the create action).
    assert '<form method="post" action="/casas-acogida/casa-123/update"' in body


# --- 12. POST /casas-acogida/{id}/update (404 when missing) --------------


async def test_update_casa_acogida_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``update_casa_acogida`` returning ``None`` -> 404."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "update_casa_acogida", lambda _c, _id, _p: None
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/missing/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-foster",
    )

    assert response.status_code == 404


# --- 13. POST /casas-acogida/{id}/delete (happy path) --------------------


async def test_delete_casa_acogida_redirects_to_list_when_successful(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soft-delete succeeds -> 303 redirect to the list page."""
    _login_as_key_user(client)
    calls: list[tuple[SqlExecutor, str]] = []

    def fake_delete(service_client: SqlExecutor, casa_id: str) -> bool:
        calls.append((service_client, casa_id))
        return True

    monkeypatch.setattr(foster_service, "delete_casa_acogida", fake_delete)

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/delete",
        csrf_token="test-csrf-token-foster",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/casas-acogida"
    assert calls == [(route_client, "casa-123")]


# --- 14. POST /casas-acogida/{id}/delete (404 when missing) --------------


async def test_delete_casa_acogida_returns_404_when_id_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``delete_casa_acogida`` returns False -> 404 (no redirect).

    ``False`` covers both "row does not exist" and "row was already
    inactive" — the service folds both into a single sentinel. The
    route maps that to 404 (not 500, not 303) so the operator sees a
    clear "row not found" page.
    """
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "delete_casa_acogida", lambda _c, _id: False
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/missing/delete",
        csrf_token="test-csrf-token-foster",
    )

    assert response.status_code == 404


# --- 15. Defense in depth: route source has no ``.execute_sql`` ---------


def test_foster_route_source_contains_no_direct_execute_sql() -> None:
    """Static check: ``app/modules/foster/routes.py`` has no SQL.

    Defense in depth alongside the runtime ``_NoSqlRouteClient`` spy.
    If a future refactor accidentally re-introduces ``client.execute_sql``
    in the route module (the AGENTS.md §1 layer-boundary violation),
    this test fails before the runtime spy can catch it.
    """
    route_source = Path("app/modules/foster/routes.py")

    assert route_source.exists()
    assert ".execute_sql(" not in route_source.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Issue #144: a ``reader`` rol MUST be rejected by the 3 casas-acogida
# write routes (create_casa_acogida / update_casa_acogida /
# delete_casa_acogida) with 403 BEFORE the handler runs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        ("POST", "/casas-acogida", _form_data()),
        ("POST", "/casas-acogida/casa-123/update", _form_data()),
        ("POST", "/casas-acogida/casa-123/delete", None),
    ],
    ids=["create_casa_acogida", "update_casa_acogida", "delete_casa_acogida"],
)
async def test_foster_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """Reader cannot POST on any casas-acogida write route (issue #144).

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
# FOSTER-03 (#45): the detail view must NOT inject ``overrides`` into the
# template context unless the user is a developer. The ``motivo`` column
# is free text from the operator (potential PII). Defense in depth: the
# template's ``{% if user.rol == "developer" %}`` block ALSO guards the
# section, so even a forgotten context injection would not leak. These
# two tests pin the context-level guard; the template guard has its own
# review/inspection pipeline.
# ---------------------------------------------------------------------------


async def test_casa_acogida_detail_hides_overrides_for_non_developer(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-developer detail render must NOT include the override section.

    The test patches :func:`assignment_service.list_overrides_for_casa`
    with a sentinel that records every call. If the route ever calls it
    for a non-developer, the call count goes up AND the sentinel string
    leaks into the response body — both fail loud.
    """
    from app.modules.foster import assignment as assignment_service

    _login_as_key_user(client)
    casa = _casa()
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: casa
    )
    monkeypatch.setattr(
        assignment_service,
        "count_active_estancias_for_casa",
        lambda _c, _id: 0,
    )

    leaked: list[Any] = []
    monkeypatch.setattr(
        assignment_service,
        "list_overrides_for_casa",
        lambda _c, _id: leaked.append(_id) or ["SHOULD-NOT-LEAK"],
    )

    response = await client.get("/casas-acogida/casa-123")

    assert response.status_code == 200
    assert leaked == [], (
        "non-developer must NOT trigger list_overrides_for_casa; "
        f"calls captured: {leaked!r}"
    )
    # Defense in depth: the sentinel MUST NOT appear in the body.
    assert "SHOULD-NOT-LEAK" not in response.text
    # The "Histórico de overrides" header is gated by
    # {% if user.rol == "developer" %} in detail.html — for a key_user
    # it should not render at all.
    assert "Histórico de overrides" not in response.text


async def test_casa_acogida_detail_shows_overrides_for_developer(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Developer detail render MUST include the override section + rows.

    Flips ``auth_reval_rol = "developer"`` BEFORE :func:`_login_as_developer`
    so the per-request revalidation SELECT echoes the cookie's rol.
    Patches the override lookup with a one-row fixture that carries the
    sentinel motivo, then asserts the override row appears in the body
    and the section header is visible.
    """
    from app.modules.foster import assignment as assignment_service

    route_client.auth_reval_rol = "developer"
    _login_as_developer(client)
    casa = _casa()
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: casa
    )
    monkeypatch.setattr(
        assignment_service,
        "count_active_estancias_for_casa",
        lambda _c, _id: 0,
    )
    monkeypatch.setattr(
        assignment_service,
        "list_overrides_for_casa",
        lambda _c, _id: [
            assignment_service.FosterCapacityOverride(
                id="ov-1",
                casa_acogida_id="casa-123",
                animal_id="animal-1",
                operador_user_id="u-dev",
                motivo="caso urgente PII marker",
                created_at="2026-07-04T11:00:00Z",
            )
        ],
    )

    response = await client.get("/casas-acogida/casa-123")

    assert response.status_code == 200
    body = response.text
    assert "Histórico de overrides" in body
    assert "caso urgente PII marker" in body

