"""Route-layer tests for ADOPT-01 adopciones (CRUD).

Mirror of ``tests/test_entradas_routes.py`` and
``tests/test_foster_routes.py``: routes are pure HTTP / auth /
template glue. The fixture ``_NoSqlRouteClient`` enforces the
AGENTS.md layer-boundary rule (no ``client.execute_sql`` in routes).
All data access goes through ``app.modules.adopciones.service``.

Auth model (issue #144): GET endpoints use ``require_authorized_user``;
write endpoints (POST create / update / delete) use
``require_writer_user`` which composes on
``require_authorized_user`` and rejects the ``reader`` rol with 403
BEFORE the handler runs. See
``test_adopciones_write_routes_reject_reader_with_403`` for the
parametrized regression test.
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


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Install a reader session cookie; reader MUST be 403 on writes.

    Issue #144 regression test for adopciones. The revalidation SELECT
    in ``require_authorized_user`` returns the rol the cookie carries;
    the route_client spy must echo the same rol so
    ``require_writer_user`` evaluates against the writer-rols set.
    """
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
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
    calls: list[tuple[InsForgeClient, dict[str, Any], str | None]] = []

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
        *,
        actor_user_id: str | None = None,
    ) -> adopciones_service.Adopcion:
        calls.append((service_client, params, actor_user_id))
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
    # P2-3 (risk review 2026-07-04): actor_user_id flows from the auth
    # payload to the audit log via the kwarg.
    assert calls[0][2] == "u-ana"


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
        service_client: InsForgeClient,
        params: dict[str, Any],
        *,
        actor_user_id: str | None = None,
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


async def test_create_adopcion_translates_duplicate_to_409(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-1 (readability review 2026-07-04): UNIQUE clash -> 409 form.

    The service raises ``AdopcionConflictError`` (a ``ValueError``
    subclass) when InsForge returns 409 on the natural-key. The route
    catches the subclass BEFORE the generic ``ValueError`` so the
    operator sees a 409 with the Spanish conflict message, not a
    generic 422.
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
        *,
        actor_user_id: str | None = None,
    ) -> adopciones_service.Adopcion:
        raise adopciones_service.AdopcionConflictError(
            "adopcion duplicada para animal_id y fecha_adopcion"
        )

    monkeypatch.setattr(adopciones_service, "create_adopcion", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones",
        form_data=_form_data(),
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 409
    body = response.text
    assert "Ya existe una adopción para ese animal y fecha" in body
    # Operator input is preserved.
    assert 'value="María García López"' in body


async def test_create_adopcion_translates_insforge_error_to_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-2 (risk review 2026-07-04): non-409 ``InsForgeError`` -> 422.

    Previously only ``ValueError`` was caught; a CHECK constraint
    violation on ``tipo_adopcion`` or a malformed date on
    ``fecha_adopcion`` raised ``InsForgeError`` (a ``RuntimeError``,
    NOT a ``ValueError``) and bubbled out as a 500. The route now
    also catches ``InsForgeError`` so those paths render as a clean
    422 with the operator's input preserved.
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
        *,
        actor_user_id: str | None = None,
    ) -> adopciones_service.Adopcion:
        raise InsForgeError(
            status_code=400,
            body={
                "error": "violates check constraint",
                "constraint": "adopciones_tipo_adopcion_check",
            },
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
    # The raw InsForge message is included so the operator can act on it.
    assert "violates check constraint" in body
    # Operator input is preserved.
    assert 'value="María García López"' in body


async def test_create_adopcion_with_bad_fecha_returns_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-2 (risk review 2026-07-04): malformed date -> 422, not 500.

    The service lets ``_optional_date`` pass the raw string through
    (validation lives in the DB). A malformed ``fecha_adopcion`` (e.g.
    ``"ayer"``) raises ``InsForgeError`` when the DB rejects the value.
    The route catches ``InsForgeError`` and renders a 422.
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
        *,
        actor_user_id: str | None = None,
    ) -> adopciones_service.Adopcion:
        raise InsForgeError(
            status_code=400,
            body={
                "error": "invalid input syntax for type date: 'ayer'",
            },
        )

    monkeypatch.setattr(adopciones_service, "create_adopcion", fake_create)

    bad_form = {**_form_data(), "fecha_adopcion": "ayer"}
    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones",
        form_data=bad_form,
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 422
    assert "invalid input syntax for type date" in response.text


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
    # ADOPT-03 (issue #49): fresh adopcion has seguimiento_estado NULL;
    # the template treats NULL as PENDIENTE (the implicit initial state).
    assert "Seguimiento: PENDIENTE" in body


async def test_adopcion_detail_renders_seguimiento_estado_when_set(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail renders the actual seguimiento_estado value when set.

    Pins the contract that the badge reflects the persisted
    ``seguimiento_estado`` after a state transition (e.g.
    DOCUMENTO_ENTREGADO, DOCUMENTO_ADJUNTO, SEGUIMIENTO_COMPLETADO),
    not the implicit PENDIENTE.
    """
    _login_as_key_user(client)
    adopcion = _adopcion()
    adopcion_with_estado = adopciones_service.Adopcion(
        id=adopcion.id,
        animal_id=adopcion.animal_id,
        fecha_adopcion=adopcion.fecha_adopcion,
        nombre_adoptante=adopcion.nombre_adoptante,
        activo=adopcion.activo,
        voluntario_seguimiento_id=adopcion.voluntario_seguimiento_id,
        fecha_devolucion=adopcion.fecha_devolucion,
        donativo_preadopcion=adopcion.donativo_preadopcion,
        donativo_adopcion=adopcion.donativo_adopcion,
        dni_adoptante=adopcion.dni_adoptante,
        telefono_adoptante=adopcion.telefono_adoptante,
        email_adoptante=adopcion.email_adoptante,
        entrada_origen_id=adopcion.entrada_origen_id,
        observaciones=adopcion.observaciones,
        tipo_adopcion=adopcion.tipo_adopcion,
        seguimiento_estado="DOCUMENTO_ENTREGADO",
    )
    monkeypatch.setattr(
        adopciones_service, "get_adopcion_by_id", lambda _c, _id: adopcion_with_estado
    )

    response = await client.get("/adopciones/adop-123")

    assert response.status_code == 200
    body = response.text
    assert "Seguimiento: DOCUMENTO_ENTREGADO" in body, (
        f"detail must render the persisted seguimiento_estado badge; "
        f"body excerpt: {body[:500]!r}"
    )


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
    calls: list[tuple[InsForgeClient, str, dict[str, Any], str | None]] = []

    def fake_update(
        service_client: InsForgeClient,
        adopcion_id: str,
        params: dict[str, Any],
        *,
        actor_user_id: str | None = None,
    ) -> adopciones_service.Adopcion | None:
        calls.append((service_client, adopcion_id, params, actor_user_id))
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
    assert calls[0][3] == "u-ana"


async def test_update_adopcion_returns_404_when_row_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Update returns 404 when the service returns ``None`` (id missing)."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        adopciones_service,
        "update_adopcion",
        lambda _c, _id, _p, *, actor_user_id=None: None,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones/missing/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 404


async def test_update_adopcion_translates_duplicate_to_409(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2-1 (risk review 2026-07-04): UNIQUE clash on update -> 409.

    Mirrors the create path: ``AdopcionConflictError`` is caught
    separately so editing a row to clash with an existing adoption
    renders a 409, not a 500.
    """
    _login_as_key_user(client)

    def fake_update(
        service_client: InsForgeClient,
        adopcion_id: str,
        params: dict[str, Any],
        *,
        actor_user_id: str | None = None,
    ) -> adopciones_service.Adopcion | None:
        raise adopciones_service.AdopcionConflictError(
            "adopcion duplicada para animal_id y fecha_adopcion"
        )

    monkeypatch.setattr(adopciones_service, "update_adopcion", fake_update)

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones/adop-123/update",
        form_data=_form_data(),
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 409
    body = response.text
    assert "Ya existe una adopción para ese animal y fecha" in body
    assert 'value="María García López"' in body


# --- 11. POST /adopciones/{id}/delete (delete, happy path) --------------


async def test_delete_adopcion_redirects_to_list(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soft-delete redirects to /adopciones when the service returns True."""
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, str, str | None]] = []

    def fake_delete(
        service_client: InsForgeClient,
        adopcion_id: str,
        *,
        actor_user_id: str | None = None,
    ) -> bool:
        calls.append((service_client, adopcion_id, actor_user_id))
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
    assert calls == [(route_client, "adop-123", "u-ana")]


async def test_delete_adopcion_returns_404_when_row_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delete returns 404 when the service returns False (id missing)."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        adopciones_service,
        "delete_adopcion",
        lambda _c, _id, *, actor_user_id=None: False,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/adopciones/missing/delete",
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 404


# --- 12. P1-3 (risk review): reader rol is rejected on writes ------------


@pytest.mark.parametrize(
    ("method", "path", "form_data"),
    [
        ("POST", "/adopciones", _form_data()),
        ("POST", "/adopciones/adop-123/update", _form_data()),
        ("POST", "/adopciones/adop-123/delete", None),
    ],
)
async def test_adopciones_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """Reader rol is forbidden on every adopciones write route (issue #144).

    Before the P1-3 fix, a reader could POST / DELETE adopciones
    because the routes used ``require_authorized_user`` (no rol gate).
    The fix layers ``require_writer_user`` over
    ``require_authorized_user``; the reader is rejected with 403
    BEFORE the handler runs, so no SQL is emitted and no template is
    rendered. GET routes (list / detail / edit / new) remain open to
    readers — only writes are gated.
    """
    route_client.auth_reval_rol = "reader"
    _login_as_reader(client)

    # Patch every service entry point the routes might call. None of
    # them should fire because ``require_writer_user`` short-circuits
    # at the dep level; if any of these would be invoked, the test
    # fails loudly via AssertionError in the patched function.
    def _never_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            f"reader POST MUST NOT reach the service; got {args=} {kwargs=}"
        )

    monkeypatch.setattr(adopciones_service, "create_adopcion", _never_called)
    monkeypatch.setattr(adopciones_service, "update_adopcion", _never_called)
    monkeypatch.setattr(adopciones_service, "delete_adopcion", _never_called)

    response = await make_csrf_request(
        client, method, path, form_data=form_data
    )

    assert response.status_code == 403, (
        f"reader rol MUST be rejected on write routes; got {response.status_code} "
        f"on {method} {path}"
    )
    # Audit log: the rejection goes through ``log_safe("auth.denied",
    # reason="writer_required", user_id=...)``; we do not assert that
    # here because the auth-denied audit lives in a different module.


# --- 12b. PATCH /adopciones/{id}/seguimiento (state machine) -----------


async def test_patch_seguimiento_invalid_transition_returns_422_with_spanish_message(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH on an invalid (estado, action) pair -> 422 + Spanish message.

    Pins the contract documented in
    ``app/modules/adopciones/service.py``: ``transition_seguimiento_for_route``
    wraps the service's ``ValueError`` (invalid transition from
    ``_next_estado``) into a ``_SeguirTransitionError`` with
    ``status_code=422`` so the route renders the form with the Spanish
    message instead of leaking a 500.
    """
    _login_as_key_user(client)

    def fake_for_route(*_args: Any, **_kwargs: Any) -> adopciones_service._SeguirTransitionError:
        return adopciones_service._SeguirTransitionError(
            message="invalid transition: estado=SEGUIMIENTO_COMPLETADO action=marcar_entregado, valid actions from SEGUIMIENTO_COMPLETADO: none",
            status_code=422,
        )

    monkeypatch.setattr(
        adopciones_service, "transition_seguimiento_for_route", fake_for_route
    )

    response = await make_csrf_request(
        client,
        "PATCH",
        "/adopciones/adop-123/seguimiento",
        form_data={"action": "marcar_entregado"},
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 422, response.text
    body = response.text
    assert "No se pudo guardar la adopci" in body, (
        f"422 response must render the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    assert "invalid transition" in body, (
        f"422 response must carry the service's 'invalid transition' "
        f"message; body excerpt: {body[:500]!r}"
    )


async def test_patch_seguimiento_anexar_without_url_returns_422_with_spanish_message(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH ``action=anexar_documento`` without ``documento_url`` -> 422.

    Pins the contract documented in
    ``app/modules/adopciones/service.py::transition_seguimiento``: the
    service raises ``ValueError("documento_url is required for action
    ANEXAR")`` when ``action == ANEXAR`` and ``documento_url is None``.
    The route wrapper must convert that to a 422 form re-render so the
    operator sees the Spanish message instead of an unhandled 500.
    """
    _login_as_key_user(client)

    def fake_for_route(*_args: Any, **_kwargs: Any) -> adopciones_service._SeguirTransitionError:
        return adopciones_service._SeguirTransitionError(
            message="documento_url is required for action ANEXAR",
            status_code=422,
        )

    monkeypatch.setattr(
        adopciones_service, "transition_seguimiento_for_route", fake_for_route
    )

    response = await make_csrf_request(
        client,
        "PATCH",
        "/adopciones/adop-123/seguimiento",
        form_data={"action": "anexar_documento", "documento_url": ""},
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 422, response.text
    body = response.text
    assert "No se pudo guardar la adopci" in body, (
        f"422 response must render the Spanish form error header; "
        f"body excerpt: {body[:500]!r}"
    )
    assert "documento_url is required" in body, (
        f"422 response must carry the service's 'documento_url is required' "
        f"message; body excerpt: {body[:500]!r}"
    )


async def test_patch_seguimiento_unknown_action_returns_422_with_spanish_message(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH with an unknown action name -> 422 (not 500).

    ``resolve_seguimiento_action`` raises ``ValueError("Accion
    desconocida: ... ")`` when the action string is not in the
    ``_ACCION_MAP``. The route wrapper must convert that to a 422 form
    re-render so the operator sees the Spanish message.
    """
    _login_as_key_user(client)

    def fake_for_route(*_args: Any, **_kwargs: Any) -> adopciones_service._SeguirTransitionError:
        return adopciones_service._SeguirTransitionError(
            message="Accion desconocida: bogus. Valores validos: marcar_entregado, anexar_documento, completar",
            status_code=422,
        )

    monkeypatch.setattr(
        adopciones_service, "transition_seguimiento_for_route", fake_for_route
    )

    response = await make_csrf_request(
        client,
        "PATCH",
        "/adopciones/adop-123/seguimiento",
        form_data={"action": "bogus"},
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 422, response.text
    body = response.text
    assert "Accion desconocida" in body, (
        f"422 response must carry the service's 'Accion desconocida' "
        f"message; body excerpt: {body[:500]!r}"
    )


async def test_patch_seguimiento_happy_path_returns_303_redirect(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH happy path -> 303 redirect to the adopcion detail page.

    Pins the success path: ``transition_seguimiento_for_route`` returns
    a ``SeguimientoTransitionResult`` (not an error sentinel) and the
    route responds with ``RedirectResponse(url=f"/adopciones/{id}",
    status_code=303)``.
    """
    _login_as_key_user(client)

    result = adopciones_service.SeguimientoTransitionResult(
        adopcion_id="adop-123",
        estado_anterior="PENDIENTE",
        nuevo_estado="DOCUMENTO_ENTREGADO",
        seguimiento_documento_entregado_at="2026-08-28T10:00:00+00:00",
        seguimiento_documento_url=None,
        seguimiento_completado_at=None,
    )

    def fake_for_route(*_args: Any, **_kwargs: Any) -> adopciones_service.SeguimientoTransitionResult:
        return result

    monkeypatch.setattr(
        adopciones_service, "transition_seguimiento_for_route", fake_for_route
    )

    response = await make_csrf_request(
        client,
        "PATCH",
        "/adopciones/adop-123/seguimiento",
        form_data={"action": "marcar_entregado"},
        csrf_token="test-csrf-token-adopciones",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/adopciones/adop-123"


# --- 13. Defense in depth: no client.execute_sql in routes source -------


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
