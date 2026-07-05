"""Route-layer tests for FOSTER-04 (#46) materiales catalog.

PR B scope: catalog CRUD routes only (the per-estancia junction routes
land in PR C). Mirrors ``tests/test_foster_routes.py`` and
``tests/test_adopciones_routes.py``: routes are pure HTTP / auth /
template glue. The fixture ``_NoSqlRouteClient`` enforces AGENTS.md §1
(no ``client.execute_sql`` in routes). All data access delegates to
``app.modules.materiales.service``.

Coverage (14 atoms):

1. Auth guard on every endpoint (parametrized over the 7 catalog
   endpoints).
2. ``GET /materiales`` delegates to ``materiales_service.list_materials``
   and renders the catalog row data from
   ``app/templates/materiales/list.html``.
3. ``GET /materiales/new`` renders the empty form with a CSRF token
   and ``form_action="/materiales"``.
4. ``POST /materiales`` with valid records redirects to the detail page
   (303).
5. ``POST /materiales`` with the service raising ``MaterialConflictError``
   renders the form with 409 + the Spanish actionable message.
6. ``POST /materiales`` with the service raising ``ValueError``
   re-renders the form with 422 + preserves operator input.
7. ``POST /materiales`` requires CSRF token — a missing token is
   rejected with 403 BEFORE the handler runs.
8. ``GET /materiales/{id}`` returns 404 when the row is missing.
9. ``GET /materiales/{id}`` renders the detail view + assigned-estancias
   stub (PR C fills in the junction data).
10. ``GET /materiales/{id}/edit`` renders the form prefilled + the
    ``/materiales/{id}/edit`` form action.
11. ``POST /materiales/{id}/edit`` with valid records redirects to the
    detail page.
12. ``POST /materiales/{id}/deactivate`` soft-deletes and redirects to
    the list (303) when the service returns True; 404 when False.
13. Reader rejected on every write route (3 endpoints) with 403 BEFORE
    the handler runs — issue #144.
14. Defense in depth: route source contains no ``.execute_sql`` call.
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
from app.modules.materiales import service as materiales_service
from tests.conftest import auth_reval_rows, make_csrf_request

# --- helpers --------------------------------------------------------------


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly.

    Mirrors ``tests/test_foster_routes.py``. Routes own no SQL; they
    delegate to the service. The single legitimate SELECT is the
    per-request authorization revalidation that
    ``require_authorized_user`` issues — answered by
    :func:`auth_reval_rows` and never re-asserted by the spy.
    """

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user``; reader
        # rejection tests flip this to ``reader``.
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
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
    """Mint a writer session cookie with a known CSRF token bound to it.

    ``key_user`` is in :attr:`Settings.writer_rols` (issue #144), so
    this cookie passes ``require_writer_user``.
    """
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-materiales",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Mint a reader session. ``reader`` is NOT in ``writer_rols`` so
    ``require_writer_user`` MUST reject with 403.

    Caller MUST flip ``route_client.auth_reval_rol = "reader"`` BEFORE
    this helper so the per-request revalidation SELECT echoes the
    cookie's rol (otherwise the cache could surface a stale role).
    """
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-materiales",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _material(
    *,
    id: str = "mat-123",
    material: str = "Cama",
    tamano: str = "Grande",
    color: str = "Azul",
    observaciones: str | None = None,
    activo: bool = True,
) -> materiales_service.Material:
    """Canonical Material fixture for assertions."""
    return materiales_service.Material(
        id=id,
        material=material,
        tamano=tamano,
        color=color,
        activo=activo,
        observaciones=observaciones,
        fecha_alta="2026-07-05T10:00:00Z",
        fecha_baja=None,
        updated_at="2026-07-05T10:00:00Z",
    )


def _form_data(
    *,
    material: str = "Cama",
    tamano: str = "Grande",
    color: str = "Azul",
    observaciones: str = "",
) -> dict[str, str]:
    """Canonical form payload for create/update POSTs.

    All values are strings so they survive httpx form-encoded transport.
    Blank ``observaciones`` is the normal "operator left it empty" case.
    """
    return {
        "material": material,
        "tamano": tamano,
        "color": color,
        "observaciones": observaciones,
    }


# --- 1. Auth guards -------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/materiales"),
        ("GET", "/materiales/new"),
        ("POST", "/materiales"),
        ("GET", "/materiales/mat-123"),
        ("GET", "/materiales/mat-123/edit"),
        ("POST", "/materiales/mat-123/edit"),
        ("POST", "/materiales/mat-123/deactivate"),
    ],
)
async def test_materiales_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every catalog endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. GET /materiales (list) -------------------------------------------


async def test_get_materiales_list_renders_table(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List endpoint delegates to the service and renders the catalog table.

    Verifies three properties at once:

    - The route calls ``materiales_service.list_materials(client,
      activos_solo=True)`` exactly once, passing the dependency-injected
      client.
    - The list HTML renders the material row (the canonical
      ``Cama | Grande | Azul | Activo`` line) in Spanish copy.
    - The "Nuevo material" button is rendered for the writer (key_user)
      session.
    """
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, bool]] = []
    material = _material()

    def fake_list(
        service_client: InsForgeClient, activos_solo: bool = True
    ) -> list[materiales_service.Material]:
        calls.append((service_client, activos_solo))
        return [material]

    monkeypatch.setattr(materiales_service, "list_materials", fake_list)

    response = await client.get("/materiales")

    assert response.status_code == 200
    assert calls == [(route_client, True)]
    body = response.text
    assert "Catálogo de materiales" in body
    assert "Cama" in body
    assert "Grande" in body
    assert "Azul" in body
    # Writer sees the create button.
    assert 'href="/materiales/new"' in body


# --- 3. GET /materiales/new (empty form) ----------------------------------


async def test_get_materiales_new_renders_form_with_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """The ``/new`` form renders with a hidden CSRF input and the create
    action pointing at ``/materiales`` (create endpoint, NOT update)."""
    _login_as_key_user(client)

    response = await client.get("/materiales/new")

    assert response.status_code == 200
    body = response.text
    # CSRF defense-in-depth token field (REQ-AH-7, AGENTS.md §10).
    assert 'name="csrf_token"' in body
    # Create endpoint, not the update endpoint.
    assert '<form method="post" action="/materiales"' in body
    # The form owns the 4 catalog fields.
    assert 'name="material"' in body
    assert 'name="tamano"' in body
    assert 'name="color"' in body
    assert 'name="observaciones"' in body


# --- 4. POST /materiales (create, happy path) -----------------------------


async def test_post_materiales_creates_and_redirects(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid create form -> service returns the material -> 303 to detail."""
    _login_as_key_user(client)
    material = _material()
    calls: list[tuple[InsForgeClient, dict[str, Any]]] = []

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> materiales_service.Material:
        calls.append((service_client, params))
        return material

    monkeypatch.setattr(materiales_service, "create_material", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/materiales",
        form_data=_form_data(),
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/materiales/mat-123"
    # The service received the dependency-injected client and the
    # operator's form payload.
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1]["material"] == "Cama"
    assert calls[0][1]["tamano"] == "Grande"
    assert calls[0][1]["color"] == "Azul"


# --- 5. POST /materiales (duplicate -> 409) -------------------------------


async def test_post_materiales_duplicate_returns_409(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MaterialConflictError`` from the service -> HTTP 409 + Spanish msg.

    Mirrors the entradas / cesiones / adopciones precedent: the DB
    ``UNIQUE (material, tamano, color)`` constraint surfaces as a
    service ``ValueError`` subclass which the route maps to a separate
    409 status (not the generic 422), so the operator sees a clear,
    actionable message in Spanish.
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> materiales_service.Material:
        raise materiales_service.MaterialConflictError(
            "ya existe material con esa combinacion material+tamano+color"
        )

    monkeypatch.setattr(materiales_service, "create_material", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/materiales",
        form_data=_form_data(),
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 409
    body = response.text
    assert "ya existe material con esa combinación" in body
    # Operator input is preserved so they can fix and retry.
    assert 'value="Cama"' in body


# --- 6. POST /materiales (validation -> 422) ------------------------------


async def test_post_materiales_validation_rejects_blank_fields(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service raises ``ValueError`` (e.g. blank material) -> 422 HTML.

    The route catches ``ValueError`` (NOT ``MaterialConflictError``)
    and re-renders the form with 422 + the operator's input preserved
    so they can fix the failing field without retyping. Mirrors the
    foster pattern (test ``test_create_casa_acogida_sad_validation``).
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> materiales_service.Material:
        raise ValueError(
            "material es obligatorio y no puede estar vacio"
        )

    monkeypatch.setattr(materiales_service, "create_material", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/materiales",
        form_data=_form_data(),
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 422
    body = response.text
    assert "No se pudo guardar el material" in body
    assert "material es obligatorio" in body
    # Operator input is preserved.
    assert 'value="Cama"' in body


# --- 7. POST /materiales (CSRF required) ----------------------------------


async def test_post_materiales_requires_csrf_token(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST without a CSRF token is rejected by ``CsrfMiddleware`` with 403.

    AGENTS.md §10 mandates the CSRF middleware on every state-changing
    route. A token must arrive either as the ``X-CSRFToken`` header
    (HTMX/fetch) or as a ``csrf_token`` form field (traditional form
    posts). This test sends NEITHER and asserts the 403.

    Sentinel: the service mock raises AssertionError if invoked — the
    CSRF layer MUST short-circuit before the handler runs.
    """
    _login_as_key_user(client)
    service_calls: list[Any] = []

    def _create_must_not_run(
        service_client: InsForgeClient, params: dict[str, Any]
    ) -> materiales_service.Material:
        service_calls.append(params)
        raise AssertionError(
            "CSRF middleware must reject missing token BEFORE service "
            f"is called; got params={params!r}"
        )

    monkeypatch.setattr(
        materiales_service, "create_material", _create_must_not_run
    )

    # No csrf_token in headers, no csrf_token in the form body.
    response = await client.post(
        "/materiales",
        data=_form_data(),
        follow_redirects=False,
    )

    assert response.status_code == 403, (
        f"missing CSRF token MUST trigger 403; got "
        f"status={response.status_code} body={response.text!r}"
    )
    assert service_calls == [], (
        "service must not be called when CSRF token is missing"
    )


# --- 8. GET /materiales/{id} (detail, missing) ---------------------------


async def test_get_material_by_id_returns_404_when_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail returns 404 when ``get_material_by_id`` returns None."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        materiales_service, "get_material_by_id", lambda _c, _id: None
    )

    response = await client.get("/materiales/missing-uuid")

    assert response.status_code == 404


# --- 9. GET /materiales/{id} (detail, happy path) -----------------------


async def test_get_material_by_id_renders_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail view renders the material's data + edit/deactivate buttons.

    PR B leaves the assigned-estancias section as an empty stub (PR C
    fills in the junction data via ``list_materials_for_estancia``).
    The detail still renders the catalog fields and the writer-only
    actions.
    """
    _login_as_key_user(client)
    material = _material(observaciones="Para el gato nuevo")
    monkeypatch.setattr(
        materiales_service,
        "get_material_by_id",
        lambda _c, _id: material,
    )

    response = await client.get("/materiales/mat-123")

    assert response.status_code == 200
    body = response.text
    assert "Cama" in body
    assert "Grande" in body
    assert "Azul" in body
    assert "Para el gato nuevo" in body
    # Edit + deactivate (deactivate form posts to /deactivate).
    assert 'href="/materiales/mat-123/edit"' in body
    assert 'action="/materiales/mat-123/deactivate"' in body
    # PR C stub for the junction section is visible.
    assert "Estancias donde está asignado" in body


# --- 10. GET /materiales/{id}/edit (edit form) --------------------------


async def test_get_material_by_id_edit_renders_form_with_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit form prefills + posts to ``/materiales/{id}/edit`` (not /new)."""
    _login_as_key_user(client)
    material = _material(observaciones="Para el gato nuevo")
    monkeypatch.setattr(
        materiales_service,
        "get_material_by_id",
        lambda _c, _id: material,
    )

    response = await client.get("/materiales/mat-123/edit")

    assert response.status_code == 200
    body = response.text
    # CSRF token field.
    assert 'name="csrf_token"' in body
    # Edit action, not create.
    assert '<form method="post" action="/materiales/mat-123/edit"' in body
    # Prefilled values.
    assert 'value="Cama"' in body
    assert 'value="Grande"' in body
    assert 'value="Azul"' in body
    assert "Para el gato nuevo" in body


# --- 11. POST /materiales/{id}/edit (update, happy path) -----------------


async def test_post_materiales_id_edit_updates_and_redirects(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid update -> service returns the material -> 303 to detail."""
    _login_as_key_user(client)
    updated = _material(color="Verde")
    calls: list[tuple[InsForgeClient, str, dict[str, Any]]] = []

    def fake_update(
        service_client: InsForgeClient,
        material_id: str,
        params: dict[str, Any],
    ) -> materiales_service.Material | None:
        calls.append((service_client, material_id, params))
        return updated

    monkeypatch.setattr(materiales_service, "update_material", fake_update)

    response = await make_csrf_request(
        client,
        "POST",
        "/materiales/mat-123/edit",
        form_data=_form_data(color="Verde"),
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/materiales/mat-123"
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1] == "mat-123"
    assert calls[0][2]["color"] == "Verde"


# --- 12. POST /materiales/{id}/deactivate --------------------------------


async def test_post_materiales_id_deactivate_soft_deletes(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deactivate succeeds (service True) -> 303 redirect to list."""
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, str]] = []

    def fake_deactivate(
        service_client: InsForgeClient, material_id: str
    ) -> bool:
        calls.append((service_client, material_id))
        return True

    monkeypatch.setattr(
        materiales_service, "deactivate_material", fake_deactivate
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/materiales/mat-123/deactivate",
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/materiales"
    assert calls == [(route_client, "mat-123")]


async def test_post_materiales_id_deactivate_returns_404_when_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``deactivate_material`` returning False -> 404 (not redirect).

    ``False`` covers "row does not exist" AND "row was already
    inactive" — the service folds both into a single sentinel. Mirrors
    the foster ``test_delete_casa_acogida_returns_404_when_id_missing``
    pattern.
    """
    _login_as_key_user(client)
    monkeypatch.setattr(
        materiales_service,
        "deactivate_material",
        lambda _c, _id: False,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/materiales/missing/deactivate",
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 404


# --- 13. RBAC: reader rejected on write routes (issue #144) --------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        ("POST", "/materiales", _form_data()),
        ("POST", "/materiales/mat-123/edit", _form_data()),
        ("POST", "/materiales/mat-123/deactivate", None),
    ],
    ids=[
        "create_material",
        "update_material",
        "deactivate_material",
    ],
)
async def test_materiales_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """A ``reader`` rol MUST be rejected on every materiales write route.

    The no-SQL spy raises AssertionError on any non-revalidation
    query — a silent pass-through into a writer dep would crash the
    test loud-and-clear, in addition to the explicit 403 check.
    """
    route_client.auth_reval_rol = "reader"
    _login_as_reader(client)

    response = await make_csrf_request(
        client, method, path, form_data=form_data
    )

    assert response.status_code == 403, (
        f"reader {method} {path} MUST be 403; got {response.status_code}"
    )
    assert "Permisos insuficientes" in response.text, (
        f"reader 403 response MUST carry 'Permisos insuficientes'; "
        f"got body: {response.text!r}"
    )


# --- 14. Defense in depth: route source has no `.execute_sql` ----------


def test_materiales_route_source_contains_no_direct_execute_sql() -> None:
    """Static check: ``app/modules/materiales/routes.py`` has no SQL.

    Defense in depth alongside the runtime ``_NoSqlRouteClient`` spy.
    If a future refactor re-introduces ``client.execute_sql`` in the
    route module (the AGENTS.md §1 layer-boundary violation), this
    test fails BEFORE the runtime spy can catch it.
    """
    route_source = Path("app/modules/materiales/routes.py")

    assert route_source.exists()
    assert ".execute_sql(" not in route_source.read_text(encoding="utf-8")
