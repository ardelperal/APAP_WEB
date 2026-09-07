"""Route-layer tests for FOSTER-04 (#46) materiales.

PR B + PR C scope: catalog CRUD routes (PR B) + per-estancia junction
routes (PR C). Mirrors ``tests/test_foster_routes.py`` and
``tests/test_adopciones_routes.py``: routes are pure HTTP / auth /
template glue. The fixture ``_NoSqlRouteClient`` enforces AGENTS.md §1
(no ``client.execute_sql`` in routes). All data access delegates to
``app.modules.materiales.service``.

Coverage (17 atoms; 14 catalog + 3 junction):

Catalog (PR B):
1. Auth guard on every catalog endpoint (parametrized over 7 endpoints).
2. ``GET /materiales`` delegates to ``list_materials`` and renders the
   catalog row data from ``app/templates/materiales/list.html``.
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
   stub (no junction data: the per-material assigned-stays list is a
   future slice).
10. ``GET /materiales/{id}/edit`` renders the form prefilled + the
    ``/materiales/{id}/edit`` form action.
11. ``POST /materiales/{id}/edit`` with valid records redirects to the
    detail page.
12. ``POST /materiales/{id}/deactivate`` soft-deletes and redirects to
    the list (303) when the service returns True; 404 when False.
13. Reader rejected on every WRITE route (5 endpoints — 3 catalog +
    2 junction) with 403 BEFORE the handler runs — issue #144.
14. Defense in depth: route source contains no ``.execute_sql`` call.

Junction (PR C):
15. ``GET /acogidas/{id}/materiales`` delegates to
    ``list_materials_for_estancia`` and renders the per-stay table from
    ``app/templates/acogidas/materiales.html``.
16. ``POST /acogidas/{id}/materiales`` calls ``assign_material_to_estancia``
    and 303-redirects to the per-stay list (the Spanish error message
    for closed stays / inactive materials is handled by the service
    layer; see ``tests/test_materiales.py`` atom A.8.9/A.8.10).
17. ``POST /acogidas/{id}/materiales/{mid}/delete`` soft-deletes the
    junction row via ``remove_material_from_estancia`` and 303-redirects
    to the per-stay list (404 when the row was missing or already
    inactive).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_local_backend_client_dep
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_local_backend_client
from app.modules.materiales import estancia_material_service
from app.modules.materiales import service as materiales_service
from tests.conftest import auth_reval_rows, make_csrf_request

# --- helpers --------------------------------------------------------------


class _NoSqlRouteClient(LocalPostgresExecutor):
    """Client spy that fails if a route executes SQL directly.

    Mirrors ``tests/test_foster_routes.py``. Routes own no SQL; they
    delegate to the service. The single legitimate SELECT is the
    per-request authorization revalidation that
    ``require_authorized_user`` issues — answered by
    :func:`auth_reval_rows` and never re-asserted by the spy.
    """

    def __init__(self) -> None:
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user``; reader
        # rejection tests flip this to ``reader``.
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval
        raise AssertionError(f"routes must not execute SQL directly: {query!r}")


@pytest.fixture
def route_client() -> _NoSqlRouteClient:
    spy = _NoSqlRouteClient()
    app.dependency_overrides[get_local_backend_client] = lambda: spy
    app.dependency_overrides[get_local_backend_client_dep] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_local_backend_client, None)
    app.dependency_overrides.pop(get_local_backend_client_dep, None)


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
    calls: list[tuple[LocalPostgresExecutor, bool]] = []
    material = _material()

    def fake_list(
        service_client: LocalPostgresExecutor, activos_solo: bool = True
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
    calls: list[tuple[LocalPostgresExecutor, dict[str, Any]]] = []

    def fake_create(
        service_client: LocalPostgresExecutor, params: dict[str, Any]
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
        service_client: LocalPostgresExecutor, params: dict[str, Any]
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
        service_client: LocalPostgresExecutor, params: dict[str, Any]
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
        service_client: LocalPostgresExecutor, params: dict[str, Any]
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
    calls: list[tuple[LocalPostgresExecutor, str, dict[str, Any]]] = []

    def fake_update(
        service_client: LocalPostgresExecutor,
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
    calls: list[tuple[LocalPostgresExecutor, str]] = []

    def fake_deactivate(
        service_client: LocalPostgresExecutor, material_id: str
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
        # PR C — junction write routes. Both reuse the writer-only
        # ``require_writer_user`` dep from the catalog router for
        # consistency.
        ("POST", "/acogidas/acog-123/materiales", {"material_id": "mat-123", "cantidad": "1", "notas": ""}),
        (
            "POST",
            "/acogidas/acog-123/materiales/junc-123/delete",
            None,
        ),
    ],
    ids=[
        "create_material",
        "update_material",
        "deactivate_material",
        "assign_material_to_estancia",
        "remove_material_from_estancia",
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


# --- 15. GET /acogidas/{id}/materiales (per-stay list) --------------------
# PR C — junction routes


def _estancia_material(
    *,
    id: str = "junc-123",
    estancia_id: str = "acog-123",
    material_id: str = "mat-123",
    cantidad: int = 2,
    activo: bool = True,
    notas: str | None = "Para la camada nueva",
    fecha_alta: str | None = "2026-07-05T10:00:00Z",
) -> materiales_service.EstanciaMaterial:
    """Canonical EstanciaMaterial junction-row fixture."""
    return materiales_service.EstanciaMaterial(
        id=id,
        estancia_id=estancia_id,
        material_id=material_id,
        cantidad=cantidad,
        activo=activo,
        notas=notas,
        fecha_alta=fecha_alta,
    )


async def test_get_acogidas_materiales_lists_per_estancia(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /acogidas/{id}/materiales renders the per-stay junction list.

    Verifies three properties at once:

    - The route calls ``estancia_material_service.list_materials_for_estancia``,
      passing the dependency-injected client, ``estancia_id``, and the
      ``activos_solo=True`` default.
    - The route also calls ``materiales_service.list_materials`` to
      populate the writer-only assign form dropdown (the spy sees
      this as a direct route SQL otherwise).
    - The list HTML renders the assigned material row (the
      ``Cama | Grande | Azul`` line) in Spanish copy.
    - CSRF token + writer-only assign form are emitted (defense in
      depth alongside the writer dep at POST time).
    """
    _login_as_key_user(client)
    list_calls: list[
        tuple[LocalPostgresExecutor, str, bool]
    ] = []
    catalog_calls: list[
        tuple[LocalPostgresExecutor, bool]
    ] = []
    junction = _estancia_material()
    catalog_material = _material()

    def fake_list_for_estancia(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        activos_solo: bool = True,
    ) -> list[materiales_service.EstanciaMaterial]:
        list_calls.append((service_client, estancia_id, activos_solo))
        return [junction]

    def fake_list_materials(
        service_client: LocalPostgresExecutor, activos_solo: bool = True
    ) -> list[materiales_service.Material]:
        catalog_calls.append((service_client, activos_solo))
        return [catalog_material]

    monkeypatch.setattr(
        estancia_material_service,
        "list_materials_for_estancia",
        fake_list_for_estancia,
    )
    monkeypatch.setattr(
        materiales_service, "list_materials", fake_list_materials
    )

    response = await client.get("/acogidas/acog-123/materiales")

    assert response.status_code == 200
    assert list_calls == [(route_client, "acog-123", True)]
    assert catalog_calls == [(route_client, True)]
    body = response.text
    assert "Materiales asignados" in body
    # CRITICAL-1 regression (jd-judge-a, PR #171): the per-stay list MUST
    # render the material's natural-key trio (material / tamano / color),
    # NOT the FK UUID (``row.material_id``) that the cells currently
    # show. The route enriches the context with a ``material_lookup``
    # dict keyed by ``material_id``; the template resolves each row's
    # FK to its human-readable name.
    #
    # The scope is restricted to ``<td>`` bodies so the catalog dropdown
    # (``<option value="mat-123">Cama — Grande — Azul</option>``) does
    # NOT satisfy this assertion — before the fix the dropdown is the
    # only place ``Cama``/``Grande``/``Azul`` appear, and the assigned
    # row's cells render FK UUIDs (``junc-123``, ``mat-123``,
    # ``acog-123``). The structural assertion below fails with the
    # current template and passes only when the route builds a
    # material_lookup and the template resolves row.material_id
    # through it.
    td_bodies = re.findall(r"<td[^>]*>([^<]*)</td>", body)
    assert any("Cama" in cell for cell in td_bodies), (
        "per-stay table MUST render the catalog material name 'Cama' "
        f"inside a <td>; got td_bodies={td_bodies!r}. The dropdown "
        "<option> bodies do not count — the assigned row's cells must "
        "show the catalog name, not the FK UUID."
    )
    assert any("Grande" in cell for cell in td_bodies), (
        "per-stay table MUST render the catalog tamano 'Grande' in a "
        f"<td>; got td_bodies={td_bodies!r}"
    )
    assert any("Azul" in cell for cell in td_bodies), (
        "per-stay table MUST render the catalog color 'Azul' in a "
        f"<td>; got td_bodies={td_bodies!r}"
    )
    # The FK UUID must NOT appear inside any assigned-row <td> body.
    # (It may still appear in dropdown option values, hidden form
    # fields, or delete-form actions — those are NOT <td> bodies.)
    for cell in td_bodies:
        assert "mat-123" not in cell, (
            "per-stay table <td> still contains the FK UUID 'mat-123' "
            f"instead of the catalog name: <td>{cell}</td>. Build "
            "material_lookup from the catalog and resolve "
            "row.material_id through it in the template."
        )
    # The writer-only assign form must include the CSRF token and a
    # ``material_id`` dropdown. The dropdown contents are mocked here;
    # we only assert the structural shape.
    assert 'name="csrf_token"' in body
    assert 'name="material_id"' in body
    # Back link to the parent stay detail page so the operator can
    # return without using the browser back button.
    assert 'href="/acogidas/acog-123"' in body


# --- 16. POST /acogidas/{id}/materiales (assign) --------------------------


async def test_post_acogidas_materiales_assigns_and_redirects(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid assign form -> service is called -> 303 to per-stay list.

    The happy-path call delegates to
    ``assign_material_to_estancia`` with the dependency-injected
    client, the path estancia_id, and the form-supplied
    material_id / cantidad / notas. The redirect goes to the per-stay
    list (``/acogidas/{id}/materiales``), NOT the catalog detail
    (``/materiales/{id}``) so the operator can see the assignment
    reflected immediately. The Spanish / 422 path for closed stays /
    inactive materials is covered by ``tests/test_materiales.py``
    atoms A.8.9 + A.8.10 — ``assign_material_to_estancia`` raises
    ``ValueError`` which the route layer maps to 422 (out of scope for
    PR C's route tests; the route layer catches ``ValueError`` on the
    same pattern as the catalog create).
    """
    _login_as_key_user(client)
    junction = _estancia_material()
    calls: list[
        tuple[LocalPostgresExecutor, str, str, int, str | None]
    ] = []

    def fake_assign(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        material_id: str,
        cantidad: int = 1,
        notas: str | None = None,
    ) -> materiales_service.EstanciaMaterial:
        calls.append(
            (service_client, estancia_id, material_id, cantidad, notas)
        )
        return junction

    monkeypatch.setattr(
        estancia_material_service, "assign_material_to_estancia", fake_assign
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/materiales",
        form_data={
            "material_id": "mat-123",
            "cantidad": "3",
            "notas": "Para camada recien nacida",
        },
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/acogidas/acog-123/materiales"
    assert len(calls) == 1
    assert calls[0][0] is route_client
    assert calls[0][1] == "acog-123"
    assert calls[0][2] == "mat-123"
    assert calls[0][3] == 3
    assert calls[0][4] == "Para camada recien nacida"


async def test_post_acogidas_materiales_assign_returns_409_on_duplicate(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent double-assignment surfaces as ``MaterialConflictError`` 409.

    Spec #15894 Scenario 4: the partial unique index
    ``estancia_materiales_active_unique`` catches a duplicate active
    assignment and surfaces PostgreSQL 23505; the service translates
    to ``MaterialConflictError``; the route maps that to HTTP 409.
    The full re-render-422-vs-redirect-303 split mirrors the catalog
    create path (``tests/test_materiales_routes.py`` atom 5).
    """
    _login_as_key_user(client)

    def fake_assign(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        material_id: str,
        cantidad: int = 1,
        notas: str | None = None,
    ) -> materiales_service.EstanciaMaterial:
        raise materiales_service.MaterialConflictError(
            "ese material ya esta asignado a esta estancia"
        )

    def fake_list_materials(
        service_client: LocalPostgresExecutor, activos_solo: bool = True
    ) -> list[materiales_service.Material]:
        return []

    def fake_list_for_estancia(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        activos_solo: bool = True,
    ) -> list[materiales_service.EstanciaMaterial]:
        return []

    monkeypatch.setattr(
        estancia_material_service, "assign_material_to_estancia", fake_assign
    )
    # The 409 path re-renders the per-stay list, which fetches both
    # the assigned list and the catalog dropdown. Stub both so the
    # spy never sees a real SELECT.
    monkeypatch.setattr(
        materiales_service, "list_materials", fake_list_materials
    )
    monkeypatch.setattr(
        estancia_material_service,
        "list_materials_for_estancia",
        fake_list_for_estancia,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/materiales",
        form_data={
            "material_id": "mat-123",
            "cantidad": "1",
            "notas": "",
        },
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 409
    body = response.text
    assert "ya esta asignado" in body


async def test_post_acogidas_materiales_assign_cantidad_zero_returns_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sad edge: ``cantidad=0`` fails the DB CHECK constraint gate.

    The route converts an empty / non-positive ``cantidad`` form
    field to ``ValueError("cantidad debe ser un entero positivo
    (>= 1)")`` via ``_cantidad_or_default`` BEFORE invoking the
    service. The 422 response re-renders the per-stay list with the
    operator input preserved.
    """
    _login_as_key_user(client)

    def fake_list_materials(
        service_client: LocalPostgresExecutor, activos_solo: bool = True
    ) -> list[materiales_service.Material]:
        return []

    def fake_list_for_estancia(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        activos_solo: bool = True,
    ) -> list[materiales_service.EstanciaMaterial]:
        return []

    # Sentinel: ``assign_material_to_estancia`` MUST NOT be invoked —
    # the cantidad validation short-circuits before the service call.
    def _assign_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "cantidad=0 must short-circuit at _cantidad_or_default, "
            "not reach assign_material_to_estancia"
        )

    monkeypatch.setattr(
        estancia_material_service,
        "assign_material_to_estancia",
        _assign_must_not_run,
    )
    monkeypatch.setattr(
        materiales_service, "list_materials", fake_list_materials
    )
    monkeypatch.setattr(
        estancia_material_service,
        "list_materials_for_estancia",
        fake_list_for_estancia,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/materiales",
        form_data={
            "material_id": "mat-123",
            "cantidad": "0",
            "notas": "",
        },
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 422
    body = response.text
    assert "cantidad debe ser un entero positivo" in body


async def test_post_acogidas_materiales_assign_cantidad_invalid_returns_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sad edge: ``cantidad`` is not an integer at all.

    An operator who deletes the value and types a letter (e.g. ``"abc"``)
    gets a clear Spanish 422 from the route's ``_cantidad_or_default``
    helper instead of an opaque PostgreSQL constraint violation.
    """
    _login_as_key_user(client)

    def fake_list_materials(
        service_client: LocalPostgresExecutor, activos_solo: bool = True
    ) -> list[materiales_service.Material]:
        return []

    def fake_list_for_estancia(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        activos_solo: bool = True,
    ) -> list[materiales_service.EstanciaMaterial]:
        return []

    def _assign_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "cantidad=abc must short-circuit at _cantidad_or_default"
        )

    monkeypatch.setattr(
        estancia_material_service,
        "assign_material_to_estancia",
        _assign_must_not_run,
    )
    monkeypatch.setattr(
        materiales_service, "list_materials", fake_list_materials
    )
    monkeypatch.setattr(
        estancia_material_service,
        "list_materials_for_estancia",
        fake_list_for_estancia,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/materiales",
        form_data={
            "material_id": "mat-123",
            "cantidad": "abc",
            "notas": "",
        },
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 422
    assert "cantidad debe ser un entero positivo" in response.text


async def test_post_acogidas_materiales_assign_value_error_returns_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service-level ValueError -> 422 (closed stay / inactive material).

    Spec #15894 Scenarios 8 + Q5: the service's
    ``assign_material_to_estancia`` validates the estancia is open
    / active AND the material is active BEFORE the INSERT. A failed
    validation raises ``ValueError``; the route layer surfaces it
    as 422 with the Spanish actionable message, then re-renders the
    per-stay list so the operator can pick a different material.
    """
    _login_as_key_user(client)

    def fake_assign(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        material_id: str,
        cantidad: int = 1,
        notas: str | None = None,
    ) -> materiales_service.EstanciaMaterial:
        raise ValueError(
            "material_id debe apuntar a un material activo (inactivo)"
        )

    def fake_list_materials(
        service_client: LocalPostgresExecutor, activos_solo: bool = True
    ) -> list[materiales_service.Material]:
        return []

    def fake_list_for_estancia(
        service_client: LocalPostgresExecutor,
        estancia_id: str,
        activos_solo: bool = True,
    ) -> list[materiales_service.EstanciaMaterial]:
        return []

    monkeypatch.setattr(
        estancia_material_service, "assign_material_to_estancia", fake_assign
    )
    monkeypatch.setattr(
        materiales_service, "list_materials", fake_list_materials
    )
    monkeypatch.setattr(
        estancia_material_service,
        "list_materials_for_estancia",
        fake_list_for_estancia,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/materiales",
        form_data={
            "material_id": "mat-inactive",
            "cantidad": "1",
            "notas": "",
        },
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 422
    assert "material activo" in response.text


# --- 17. POST /acogidas/{id}/materiales/{mid}/delete ----------------------


async def test_post_acogidas_materiales_mid_delete_soft_deletes(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid delete -> service returns True -> 303 to per-stay list."""
    _login_as_key_user(client)
    calls: list[tuple[LocalPostgresExecutor, str]] = []

    def fake_remove(
        service_client: LocalPostgresExecutor, junction_id: str
    ) -> bool:
        calls.append((service_client, junction_id))
        return True

    monkeypatch.setattr(
        estancia_material_service,
        "remove_material_from_estancia",
        fake_remove,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/materiales/junc-123/delete",
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 303
    assert (
        response.headers["location"] == "/acogidas/acog-123/materiales"
    )
    assert calls == [(route_client, "junc-123")]


async def test_post_acogidas_materiales_mid_delete_returns_404_when_missing(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``remove_material_from_estancia`` returning False -> 404.

    Same shape as ``deactivate_material``: ``False`` covers "row
    does not exist" AND "row was already inactive" — the service
    folds both into a single sentinel.
    """
    _login_as_key_user(client)
    monkeypatch.setattr(
        estancia_material_service,
        "remove_material_from_estancia",
        lambda _c, _id: False,
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/acogidas/acog-123/materiales/missing-junc/delete",
        csrf_token="test-csrf-token-materiales",
    )

    assert response.status_code == 404


def test_materiales_acogida_route_source_contains_no_direct_execute_sql() -> None:
    """Static check on the PR C junction routes module.

    Same defense-in-depth pattern as test 14: if a future refactor
    re-introduces ``client.execute_sql`` in
    ``app/modules/materiales/acogida_routes.py`` (the AGENTS.md §1
    layer-boundary violation), this test fails BEFORE the runtime
    spy can catch it.
    """
    route_source = Path("app/modules/materiales/acogida_routes.py")

    assert route_source.exists()
    assert ".execute_sql(" not in route_source.read_text(encoding="utf-8")
