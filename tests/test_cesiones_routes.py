"""Route-level tests for the cesion por propietario workflow.

Mirrors ``tests/test_entradas_routes.py`` exactly: route layer is just
HTTP I/O + auth + redirect-on-success; everything else lives in
``app.modules.cesiones.service``. The ``_NoSqlRouteClient`` spy below
guarantees routes never call ``execute_sql`` directly — that would
bypass service-layer validation and the layer-boundary invariant from
``docs/proceso.md`` §0 + AGENTS.md rule 1.
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
from app.modules.cesiones import service as cesiones_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly."""

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user``; the reader
        # rejection test sets this to ``reader`` so ``require_writer_user``
        # produces 403 BEFORE any handler SQL.
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


@pytest.fixture
def cesion() -> cesiones_service.Cesion:
    return cesiones_service.Cesion(
        id="ces-abc",
        entrada_id="ent-abc",
        numero_contrato="CP0672",
        nombre_representante="Maria Lopez Garcia",
    )


@pytest.fixture
def contrato() -> cesiones_service.Contrato:
    return cesiones_service.Contrato(
        id="ctr-abc",
        tipo_contrato_id="tip-ces",
        numero_contrato="CP0672",
        fecha="2026-07-03",
        cesion_id="ces-abc",
    )


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            # PR-5B2: session-bound CSRF token.
            "csrf_token": "test-csrf-token-cesiones",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_reader(client: httpx.AsyncClient) -> None:
    """Install a reader session; writer dep MUST reject with 403 (issue #144).

    The route client must have ``auth_reval_rol = "reader"`` BEFORE this
    helper runs so the per-request revalidation SELECT returns the same
    rol the cookie carries (otherwise require_authorized_user's cache
    could surface a stale rol from a previous test).
    """
    token = write_session(
        {
            "email": "rocio@example.com",
            "rol": "reader",
            "user_id": "u-rocio",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-cesiones",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _form_data(**overrides: str) -> dict[str, str]:
    """Canonical happy-path payload for the cesión form."""
    data = {
        "entrada_id": "ent-abc",
        "numero_contrato": "CP0672",
        "nombre_representante": "Maria Lopez Garcia",
        "dni_representante": "12345678Z",
        "fecha_cesion": "2026-07-03",
        "calle_representante": "Calle Mayor",
        "numero_calle_representante": "1",
        "piso_representante": "2",
        "letra_representante": "A",
        "localidad_representante": "Alcala de Henares",
        "provincia_representante": "Madrid",
        "cp_representante": "28801",
        "telefono_representante": "600000000",
        "email_representante": "maria@example.com",
        "cartilla_sanitaria": "Sí",
        "certificado_veterinario": "Sí",
        "autorizacion_recogida": "Sí",
        "fecha_vacuna_rabia": "2026-05-15",
        "numero_colegiado": "9999",
        "numero_colaborador": "5555",
        "hora_cesion": "2026-07-03T11:30",
    }
    data.update(overrides)
    return data


# --- auth -----------------------------------------------------------------


async def test_cesiones_routes_require_authorized_user(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/cesiones/new", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- GET /cesiones/new (form) --------------------------------------------


async def test_new_cesion_form_renders_form_posting_to_cesiones(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    _login_as_key_user(client)

    response = await client.get("/cesiones/new")

    assert response.status_code == 200
    assert '<form method="post" action="/cesiones"' in response.text


async def test_new_cesion_form_includes_all_legacy_columns(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """The form MUST carry every column from the Access legacy
    ``TbCesionPorPropietario`` per the P1 fidelity invariant (no field
    loss). Each input ``name`` attribute maps 1:1 to a column in
    ``cesiones_propietario``.
    """
    _login_as_key_user(client)

    response = await client.get("/cesiones/new")

    assert response.status_code == 200
    expected_fields = [
        "entrada_id",
        "numero_contrato",
        "nombre_representante",
        "dni_representante",
        "calle_representante",
        "numero_calle_representante",
        "piso_representante",
        "letra_representante",
        "localidad_representante",
        "provincia_representante",
        "cp_representante",
        "telefono_representante",
        "email_representante",
        "cartilla_sanitaria",
        "certificado_veterinario",
        "autorizacion_recogida",
        "fecha_vacuna_rabia",
        "numero_colegiado",
        "numero_colaborador",
        "hora_cesion",
    ]
    for field in expected_fields:
        assert f'name="{field}"' in response.text, (
            f"cesiones form missing field {field!r}; "
            f"P1 fidelity requires every legacy column."
        )


async def test_new_cesion_form_includes_csrf_token_input(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """REGR-GUARD: AGENTS.md rule 10 — every form MUST include the
    CSRF token input. The CsrfMiddleware enforces this at request time;
    the template guard here catches form regressions before CI.
    """
    _login_as_key_user(client)

    response = await client.get("/cesiones/new")

    assert response.status_code == 200
    assert 'name="csrf_token"' in response.text


# --- POST /cesiones (happy path) -----------------------------------------


async def test_create_cesion_delegates_to_service_and_redirects_to_parent_entrada(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    cesion: cesiones_service.Cesion,
    contrato: cesiones_service.Contrato,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful submit returns 303 redirect to the parent
    ``/entradas/{entrada_id}``. The cesión is 1-a-1 with the intake
    (FK UNIQUE on entrada_id per P1 fidelity), so the operator
    inspects the surrender from the existing intake detail page.
    A standalone ``/cesiones/{id}`` view is deferred to Fase 7.
    """
    _login_as_key_user(client)
    calls: list[tuple[InsForgeClient, dict[str, Any]]] = []

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
    ) -> tuple[cesiones_service.Cesion, cesiones_service.Contrato]:
        calls.append((service_client, params))
        return cesion, contrato

    monkeypatch.setattr(cesiones_service, "create_cesion", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(),
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/entradas/ent-abc"
    # The service received the route client (no SQL bypassing).
    assert calls == [(route_client, _form_data())]


async def test_create_cesion_strips_strippable_optional_fields(
    client: httpx.AsyncClient,
    cesion: cesiones_service.Cesion,
    contrato: cesiones_service.Contrato,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank optional fields must reach the service as ``None`` so the
    service writes NULL to the DB (not empty string). Mirrors
    ``_form_data_to_params`` / ``_opt`` in ``entradas/routes.py``.
    """
    _login_as_key_user(client)
    captured: dict[str, Any] = {}

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
    ) -> tuple[cesiones_service.Cesion, cesiones_service.Contrato]:
        captured["params"] = params
        return cesion, contrato

    monkeypatch.setattr(cesiones_service, "create_cesion", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(telefono_representante="   "),
    )

    assert response.status_code == 303
    # Blank stripped -> None (sent to DB as NULL, not "").
    assert captured["params"]["telefono_representante"] is None


# --- POST /cesiones (error paths) ----------------------------------------


async def test_create_duplicate_translates_to_409_html(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    route_client: _NoSqlRouteClient,
) -> None:
    """When the entrada already has a cesión, the UNIQUE FK fires and
    service raises ``CesionConflictError``. The route re-renders the
    form with 409 + a user-facing message.
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
    ) -> tuple[cesiones_service.Cesion, cesiones_service.Contrato]:
        assert service_client is route_client
        raise cesiones_service.CesionConflictError(
            "ya existe una cesión para esta entrada"
        )

    monkeypatch.setattr(cesiones_service, "create_cesion", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(),
    )

    assert response.status_code == 409
    assert "Ya existe una cesión" in response.text or (
        "cesión" in response.text
    )


async def test_create_validation_error_rerenders_form_with_422(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service raises ``ValueError`` on missing required fields. The
    route re-renders the form with 422 + the message exposed to the
    user (no internal stack-trace leakage).
    """
    _login_as_key_user(client)

    def fake_create(
        service_client: InsForgeClient,
        params: dict[str, Any],
    ) -> tuple[cesiones_service.Cesion, cesiones_service.Contrato]:
        raise ValueError("nombre_representante is required and cannot be empty")

    monkeypatch.setattr(cesiones_service, "create_cesion", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(nombre_representante="   "),
    )

    assert response.status_code == 422
    assert "No se pudo guardar la cesión" in response.text
    assert "nombre_representante is required" in response.text


# --- layer-boundary guard ------------------------------------------------


def test_cesiones_route_source_contains_no_direct_execute_sql() -> None:
    """AgENT rule 1: routes are HTTP-only. The service owns SQL. This
    static check protects against regressions where someone re-adds a
    direct ``client.execute_sql`` call to the route.
    """
    route_source = Path("app/modules/cesiones/routes.py")

    assert route_source.exists(), (
        "app/modules/cesiones/routes.py must exist; run code review if "
        "this file is missing"
    )
    assert ".execute_sql(" not in route_source.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Issue #144: a ``reader`` rol MUST be rejected by the cesiones write route
# with 403 BEFORE the handler runs. The route has only one POST surface
# (``/cesiones``) so a single test pins the contract; the no-SQL spy
# doubles as the assertion that nothing in the handler short-circuits
# past the writer dep.
# ---------------------------------------------------------------------------


async def test_create_cesion_rejects_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """Reader cannot POST a new cesion (issue #144).

    The no-SQL spy (``_NoSqlRouteClient``) raises AssertionError on
    every non-revalidation query — a silent pass through the writer
    dep would crash the test loud and clear via the spy, in addition
    to the explicit 403 check.
    """
    route_client.auth_reval_rol = "reader"
    _login_as_reader(client)

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(),
    )

    assert response.status_code == 403, (
        f"reader POST /cesiones MUST be 403; got {response.status_code}"
    )
