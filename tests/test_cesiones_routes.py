"""Route-level tests for the cesion por propietario workflow.

Routes are thin HTTP I/O + auth + redirect-on-success under the hexagonal
architecture (port-injected DI). Auth validation, SQL, validation and
domain rules live behind ``CesionesPort`` (application layer -> adapter ->
service). The ``_NoSqlRouteClient`` spy guarantees routes never call
``execute_sql`` directly -- that would bypass the port and violate the
layer boundary (AGENTS.md rule 1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_local_backend_client_dep
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_local_backend_client
from app.modules.cesiones import service as cesiones_service
from app.modules.cesiones.di import get_cesiones_port
from app.modules.cesiones.domain.cesion import Cesion, CesionConflictError, Contrato
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(LocalPostgresExecutor):
    """Client spy that fails if a route executes SQL directly."""

    def __init__(self) -> None:
        import httpx as _httpx

    def __init__(self) -> None:
        # Issue #144: rol returned by the per-request authorization
        # revalidation SELECT. Defaults to ``key_user``; reader
        # rejection tests set this to ``reader`` so
        # ``require_writer_user`` produces 403 BEFORE any handler SQL.
        self.auth_reval_rol: str = "key_user"

    def execute_sql(self, query: str, params: Any = None):
        _reval = auth_reval_rows(query, params, rol=self.auth_reval_rol)
        if _reval is not None:
            return _reval  # type: ignore[no-any-return]
        raise AssertionError(f"routes must not execute SQL directly: {query!r}")

    def close(self) -> None:
        pass  # no-op for spy
class _MockCesionesPort:
    """In-memory CesionesPort spy for hexagonal route-layer tests.

    Allows tests to control the port's return value or exception without
    touching the service layer or the DI graph.
    """

    __slots__ = ("_cesion", "_contrato", "_error", "_calls")

    def __init__(
        self,
        cesion: Cesion | None = None,
        contrato: Contrato | None = None,
        error: Exception | None = None,
    ) -> None:
        self._cesion = cesion
        self._contrato = contrato
        self._error = error
        self._calls: list[tuple[str, dict[str, Any]]] = []

    def create_cesion(self, params: dict[str, Any]) -> tuple[Cesion, Contrato]:
        self._calls.append(("create_cesion", params))
        if self._error is not None:
            raise self._error
        if self._cesion is None or self._contrato is None:
            raise RuntimeError("mock port has no cesion/contrato configured")
        return self._cesion, self._contrato

    def get_cesion_by_entrada_id(self, entrada_id: str) -> Cesion | None:
        return self._cesion if self._cesion and self._cesion.entrada_id == entrada_id else None

    def list_cesiones(self) -> list[Cesion]:
        return [self._cesion] if self._cesion else []


@pytest.fixture
def route_client() -> _NoSqlRouteClient:
    spy = _NoSqlRouteClient()
    app.state.sql_executor = spy
    # Override the DI so get_cesiones_port reads this spy (not the
    # _DefaultLocalBackendSpy from the client fixture).
    app.dependency_overrides[get_local_backend_client] = lambda: spy
    app.dependency_overrides[get_local_backend_client_dep] = lambda: spy
    # Also set app.state so get_cesiones_port (which reads request.app.state)
    # picks up this spy instead of the client fixture's _DefaultLocalBackendSpy.
    app.state.sql_executor = spy
    yield spy
    app.dependency_overrides.pop(get_local_backend_client, None)
    app.dependency_overrides.pop(get_local_backend_client_dep, None)


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _form_data(**overrides: str) -> dict[str, str]:
    """Canonical happy-path payload for the cesion form."""
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
        "cartilla_sanitaria": "Si",
        "certificado_veterinario": "Si",
        "autorizacion_recogida": "Si",
        "fecha_vacuna_rabia": "2026-01-01",
        "numero_colegiado": "COL-123",
        "numero_colaborador": "COLAB-456",
        "hora_cesion": "10:00",
    }
    data.update(overrides)
    return data


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-cesiones",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_cesiones_routes_require_authorized_user(
    client: httpx.AsyncClient,
) -> None:
    """Unauthenticated GET /cesiones/new returns 302 to /login."""
    response = await client.get("/cesiones/new", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_new_cesion_form_renders_form_posting_to_cesiones(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """GET /cesiones/new renders a form whose action points at POST /cesiones."""
    _login_as_key_user(client)
    response = await client.get("/cesiones/new")
    assert response.status_code == 200
    assert '<form method="post" action="/cesiones"' in response.text


async def test_new_cesion_form_includes_all_legacy_columns(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """The form renders every legacy TbCesionPorPropietario column."""
    _login_as_key_user(client)
    response = await client.get("/cesiones/new")
    expected_fields = [
        "nombre_representante",
        "dni_representante",
        "fecha_cesion",
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
    """The form renders a hidden CSRF token input per AGENTS.md rule 10."""
    _login_as_key_user(client)
    response = await client.get("/cesiones/new")
    assert 'name="csrf_token"' in response.text


async def test_create_cesion_delegates_to_service_and_redirects_to_parent_entrada(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    cesion: cesiones_service.Cesion,
    contrato: cesiones_service.Contrato,
) -> None:
    """Successful submit returns 303 redirect to the parent /entradas/{id}.

    The cesion is 1-a-1 with the intake (FK UNIQUE on entrada_id per P1
    fidelity), so the operator inspects the surrender from the existing
    intake detail page. A standalone /cesiones/{id} view is deferred to Fase 7.
    """
    _login_as_key_user(client)

    mock_port = _MockCesionesPort(cesion=cesion, contrato=contrato)
    app.dependency_overrides[get_cesiones_port] = lambda: mock_port

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(),
    )

    app.dependency_overrides.pop(get_cesiones_port, None)

    assert response.status_code == 303
    assert response.headers["location"] == "/entradas/ent-abc"
    # The port received the form data (no SQL bypassing at route layer).
    assert mock_port._calls == [("create_cesion", _form_data())]


async def test_create_cesion_strips_strippable_optional_fields(
    client: httpx.AsyncClient,
    cesion: cesiones_service.Cesion,
    contrato: cesiones_service.Contrato,
) -> None:
    """Blank optional fields reach the port as None so the service writes
    NULL to the DB (not empty string). Mirrors _opt in routes.py.
    """
    _login_as_key_user(client)

    mock_port = _MockCesionesPort(cesion=cesion, contrato=contrato)
    app.dependency_overrides[get_cesiones_port] = lambda: mock_port

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(telefono_representante="   "),
    )

    app.dependency_overrides.pop(get_cesiones_port, None)

    assert response.status_code == 303
    # Blank stripped -> None (sent to DB as NULL, not "").
    assert mock_port._calls[0][1]["telefono_representante"] is None


async def test_create_duplicate_translates_to_409_html(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """When the entrada already has a cesion, the service raises
    CesionConflictError (UNIQUE FK). The route re-renders the form with
    409 + a user-facing message.
    """
    _login_as_key_user(client)

    mock_port = _MockCesionesPort(
        error=CesionConflictError(
            "ya existe una cesion por propietario para esta entrada"
        ),
    )
    app.dependency_overrides[get_cesiones_port] = lambda: mock_port

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(),
    )

    app.dependency_overrides.pop(get_cesiones_port, None)

    assert response.status_code == 409
    assert "Ya existe una cesion" in response.text


async def test_create_validation_error_rerenders_form_with_422(
    client: httpx.AsyncClient,
) -> None:
    """Route raises ValueError on missing required fields. The route
    re-renders the form with 422 + the message exposed to the user
    (no internal stack-trace leakage).
    """
    _login_as_key_user(client)

    mock_port = _MockCesionesPort(
        error=ValueError("nombre_representante is required and cannot be empty"),
    )
    app.dependency_overrides[get_cesiones_port] = lambda: mock_port

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(nombre_representante="   "),
    )

    app.dependency_overrides.pop(get_cesiones_port, None)

    assert response.status_code == 422
    assert "No se pudo guardar la cesion" in response.text
    assert "nombre_representante is required" in response.text


async def test_cesiones_route_source_contains_no_direct_execute_sql(
    route_client: _NoSqlRouteClient,
) -> None:
    """AGENTS rule 1: routes are HTTP-only. The service owns SQL. This
    static check protects against regressions where someone re-adds a
    direct SQL call to the route body (outside the docstring reference).
    """
    import app.modules.cesiones.routes as mod
    source = Path(mod.__file__).read_text(encoding="utf-8")
    # Exclude the module docstring (which mentions execute_sql as a rule reference).
    # Check only the code body.
    docstring_end = source.index('"""', source.index('"""') + 3) + 3
    body = source[docstring_end:]
    assert "execute_sql" not in body, "routes must not call execute_sql directly"


async def test_create_cesion_rejects_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """A reader rol cannot create a cesion (requires key_user).

    The route requires ``WRITE_CESIONES`` permission. A reader session
    (rol=reader) triggers ``require_permission(WRITE_CESIONES)`` to fire
    a 403 BEFORE the handler runs and before any port SQL is needed.
    """
    # Install a reader session (not key_user) so the permission check fires.
    token = write_session(
        {
            "email": "reader@example.com",
            "rol": "reader",
            "user_id": "u-reader",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-cesiones",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)

    response = await make_csrf_request(
        client,
        "POST",
        "/cesiones",
        form_data=_form_data(),
    )

    assert response.status_code == 403

