"""Route-layer tests for FOSTER-03 foster assignment sub-router.

Mirrors ``tests/test_foster_routes.py`` and ``tests/test_acogidas_routes.py``:
routes are pure HTTP / auth / template glue. The fixture
``_NoSqlRouteClient`` enforces the AGENTS.md layer-boundary rule (no
``client.execute_sql`` in routes); data access goes through
``app.modules.foster.assignment``.

Coverage (15 atoms):

1.  Auth guard on every endpoint (parametrized over the 3 endpoints).
2.  GET /casas-acogida/{id}/asignar renders the form with CSRF token.
3.  GET /casas-acogida/{id}/asignar returns 404 when casa missing.
4.  POST /casas-acogida/{id}/asignar with admit -> 303 with query params.
5.  POST .../asignar with block -> 422 with error.
6.  POST .../asignar with admit_with_warning + motivo -> INSERT override + 303.
7.  POST .../asignar with admit_with_warning + empty motivo -> 422 + warning visible.
8.  POST .../asignar with animal missing -> 422 with service message.
9.  POST .../asignar with casa missing -> 404.
10. POST .../asignar with casa inactive -> 422 with 'dada de baja'.
11. POST .../asignar without CSRF -> 403.
12. GET .../overrides renders table with overrides.
13. GET .../overrides with empty list shows 'sin overrides' message.
14. Route source contains no ``client.execute_sql`` (defense in depth).
15. POST .../asignar with motivo whitespace -> 422, NO INSERT.
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
from app.modules.foster import assignment as assignment_service
from app.modules.foster import service as foster_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly.

    Mirrors the same pattern used across the codebase: routes own no
    SQL, they delegate to the service. The ``_NoSqlRouteClient`` is a
    defense-in-depth check alongside the static source scan at test 14
    below.
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
            "csrf_token": "test-csrf-token-foster-assignment",
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
            "csrf_token": "test-csrf-token-foster-assignment",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _login_as_developer(client: httpx.AsyncClient) -> None:
    """FOSTER-03 (#45): developer session for the overrides-dev-only paths.

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
            "csrf_token": "test-csrf-token-foster-assignment",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _casa() -> foster_service.CasaAcogida:
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
        capacidad=2,
    )


def _override_row(
    id_: str = "99999999-9999-9999-9999-999999999999",
    motivo: str = "caso urgente",
) -> assignment_service.FosterCapacityOverride:
    return assignment_service.FosterCapacityOverride(
        id=id_,
        casa_acogida_id="casa-123",
        animal_id="11111111-1111-1111-1111-111111111111",
        operador_user_id="u-ana",
        motivo=motivo,
        created_at="2026-07-04T11:00:00Z",
    )


# --- 1. Auth guards -------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/casas-acogida/casa-123/asignar"),
        ("POST", "/casas-acogida/casa-123/asignar"),
        ("GET", "/casas-acogida/casa-123/overrides"),
    ],
)
async def test_foster_assignment_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """Every FOSTER-03 endpoint requires a session; anonymous -> /login."""
    response = await client.request(method, path, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- 2. GET /casas-acogida/{id}/asignar renders form ----------------------


async def test_get_asignar_renderiza_form_con_csrf(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET asignar renders form with CSRF token + animal_id input."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )

    response = await client.get("/casas-acogida/casa-123/asignar")

    assert response.status_code == 200
    body = response.text
    assert 'name="animal_id"' in body
    assert 'name="csrf_token"' in body
    assert 'action="/casas-acogida/casa-123/asignar"' in body
    # Copy in castellano.
    assert "Asignar animal" in body
    assert "UUID" in body


# --- 3. GET asignar 404 when casa missing --------------------------------


async def test_get_asignar_casa_no_existe_retorna_404(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: None
    )

    response = await client.get("/casas-acogida/casa-missing/asignar")

    assert response.status_code == 404


# --- 4. POST admit -> 303 --------------------------------------------------


async def test_post_asignar_admit_redirect_303_con_query_params(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=admit -> 303 to /acogidas/new?animal_id=X&casa_acogida_id=Y."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, animal_id, casa_id: assignment_service.AssignmentDecision(
            decision="admit", reason=None, warnings=()
        ),
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={"animal_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/acogidas/new?")
    assert "animal_id=11111111-1111-1111-1111-111111111111" in location
    assert "casa_acogida_id=casa-123" in location


# --- 5. POST block -> 422 --------------------------------------------------


async def test_post_asignar_block_retorna_422_con_error(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=block -> 422 with reason visible in form re-render."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="block",
            reason="la casa solo admite FELINA, no CANINA",
            warnings=(),
        ),
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={"animal_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert response.status_code == 422
    body = response.text
    assert "la casa solo admite FELINA, no CANINA" in body
    assert "No se puede asignar" in body


# --- 6. POST admit_with_warning + motivo -> INSERT + 303 ----------------


async def test_post_asignar_admit_with_warning_con_motivo_graba_override_y_redirect(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=admit_with_warning + motivo non-empty -> INSERT override + 303.

    Issue #142: el redirect URL DEBE incluir ``override_id=<uuid>`` para
    que ``create_acogida`` pueda enlazar el override con la estancia
    resultante. Sin ese parámetro, el row de ``foster_capacity_overrides``
    queda huérfano (el operador puede cancelar el create y la auditoría
    queda mintiendo). El test pinea el contrato del redirect.
    """
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit_with_warning",
            reason=None,
            warnings=("capacidad excedida: 2/2",),
        ),
    )
    recorded: list[dict[str, Any]] = []

    # Issue #142: record_override ahora devuelve el UUID como str.
    OVERRIDE_UUID = "99999999-9999-9999-9999-999999999999"

    def _record_override(
        _c, *, casa_id, animal_id, operador_user_id, motivo
    ) -> str:
        recorded.append(
            {
                "casa_id": casa_id,
                "animal_id": animal_id,
                "operador_user_id": operador_user_id,
                "motivo": motivo,
            }
        )
        return OVERRIDE_UUID

    monkeypatch.setattr(
        assignment_service, "record_override", _record_override
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "motivo": "caso urgente",
        },
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/acogidas/new?")
    assert "animal_id=11111111-1111-1111-1111-111111111111" in location
    assert "casa_acogida_id=casa-123" in location
    # Issue #142: override_id MUST be present for the estancia-create
    # side to link the override row to the new estancia.
    assert f"override_id={OVERRIDE_UUID}" in location, (
        f"redirect MUST thread override_id for atomicity; got {location!r}"
    )
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["casa_id"] == "casa-123"
    assert entry["animal_id"] == "11111111-1111-1111-1111-111111111111"
    assert entry["operador_user_id"] == "u-ana"  # from session
    assert entry["motivo"] == "caso urgente"


async def test_post_asignar_admit_redirect_does_not_include_override_id(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=admit (no warning) -> 303 sin ``override_id`` (no override recorded).

    Regresión del cambio: cuando el gate pasa sin warning no hay override
    que enlazar, así que el redirect NO lleva ``override_id``. Esto
    garantiza que ``create_acogida`` no intente un UPDATE fantasma sobre
    un row inexistente.
    """
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit", reason=None, warnings=()
        ),
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={"animal_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "override_id=" not in location, (
        f"admit (no warning) MUST NOT include override_id; got {location!r}"
    )


# --- 7. POST admit_with_warning sin motivo -> 422 + warning visible -----


async def test_post_asignar_admit_with_warning_sin_motivo_retorna_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=admit_with_warning + motivo='' -> 422 + warning + msg."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit_with_warning",
            reason=None,
            warnings=("capacidad excedida: 2/2",),
        ),
    )
    recorded: list[Any] = []
    monkeypatch.setattr(
        assignment_service,
        "record_override",
        lambda *a, **kw: recorded.append((a, kw)) or _override_row(),
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "motivo": "",
        },
    )

    assert response.status_code == 422
    body = response.text
    assert "capacidad excedida: 2/2" in body
    assert "motivo es obligatorio" in body
    # record_override must NOT be called when motivo is empty.
    assert recorded == []


# --- 8. POST animal no existe -> 422 -------------------------------------


async def test_post_asignar_animal_no_existe_retorna_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """evaluate_assignment raises ValueError -> route 422 with service msg."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )

    def _raise(_c, _aid, _cid) -> assignment_service.AssignmentDecision:
        raise ValueError("el animal no existe o no está activo")

    monkeypatch.setattr(assignment_service, "evaluate_assignment", _raise)

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={"animal_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert response.status_code == 422
    assert "el animal no existe" in response.text


# --- 9. POST casa no existe -> 404 ---------------------------------------


async def test_post_asignar_casa_no_existe_retorna_404(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: None
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-missing/asignar",
        form_data={"animal_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert response.status_code == 404


# --- 10. POST casa inactiva -> 422 ---------------------------------------


async def test_post_asignar_casa_inactiva_retorna_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )

    def _raise(_c, _aid, _cid) -> assignment_service.AssignmentDecision:
        raise ValueError("la casa está dada de baja")

    monkeypatch.setattr(assignment_service, "evaluate_assignment", _raise)

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={"animal_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert response.status_code == 422
    assert "dada de baja" in response.text


# --- 11. POST sin CSRF -> 403 --------------------------------------------


async def test_post_asignar_sin_csrf_retorna_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CSRF middleware rejects POST without token."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit", reason=None, warnings=()
        ),
    )

    # No csrf_token in form.
    response = await client.post(
        "/casas-acogida/casa-123/asignar",
        data={"animal_id": "11111111-1111-1111-1111-111111111111"},
        follow_redirects=False,
    )

    assert response.status_code == 403


# --- 12. GET overrides renders table -------------------------------------


async def test_get_overrides_renderiza_tabla_con_overrides(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET overrides con 2 overrides -> tabla con 2 filas.

    FOSTER-03 (#45): overrides_list ahora exige ``rol == "developer"``
    (la columna ``motivo`` es texto libre del operador y puede llevar
    PII). El login se hace via :func:`_login_as_developer` y la spy
    refleja ``auth_reval_rol = "developer"`` antes del login para que
    el SELECT de revalidacion por request (#143) coincida con la cookie.
    """
    route_client.auth_reval_rol = "developer"
    _login_as_developer(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "list_overrides_for_casa",
        lambda _c, _cid: [_override_row(id_="a"), _override_row(id_="b")],
    )

    response = await client.get("/casas-acogida/casa-123/overrides")

    assert response.status_code == 200
    body = response.text
    # Template renders created_at, animal_id, motivo, operador_user_id
    # per row (id is not surfaced in the UI). The fixture override
    # carries these; assert they appear at least once.
    assert "u-ana" in body  # operador
    assert "caso urgente" in body  # motivo
    assert "11111111-1111-1111-1111-111111111111" in body  # animal_id
    # 2 rows -> 2 occurrences of the motivo (one per row).
    assert body.count("caso urgente") == 2


# --- 13. GET overrides empty -> "sin overrides" -------------------------


async def test_get_overrides_sin_overrides_muestra_mensaje_vacio(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FOSTER-03 (#45): developer-only listing.

    Mismo cambio que en test 12: developer-only. Ver la docstring
    de :func:`_login_as_developer` para el contrato del cookie + rol.
    """
    route_client.auth_reval_rol = "developer"
    _login_as_developer(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "list_overrides_for_casa",
        lambda _c, _cid: [],
    )

    response = await client.get("/casas-acogida/casa-123/overrides")

    assert response.status_code == 200
    assert "Sin overrides registrados" in response.text


# --- 14. Static check: route source has no .execute_sql ----------------


def test_foster_assignment_route_source_contains_no_direct_execute_sql() -> None:
    """Static check: ``assignment_routes.py`` has no SQL.

    Defense in depth alongside the runtime ``_NoSqlRouteClient`` spy.
    """
    route_source = Path("app/modules/foster/assignment_routes.py")

    assert route_source.exists()
    assert ".execute_sql(" not in route_source.read_text(encoding="utf-8")


# --- 15. POST admit_with_warning motivo whitespace -> 422 + NO INSERT ---


async def test_post_asignar_warning_motivo_whitespace_no_graba_override(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """motivo='   ' -> 422 + warning visible + NO INSERT."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit_with_warning",
            reason=None,
            warnings=("capacidad excedida: 2/2",),
        ),
    )
    recorded: list[Any] = []
    monkeypatch.setattr(
        assignment_service,
        "record_override",
        lambda *a, **kw: recorded.append((a, kw)) or _override_row(),
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "motivo": "   ",
        },
    )

    assert response.status_code == 422
    assert recorded == []  # record_override must NOT be called


# ---------------------------------------------------------------------------
# Issue #144: a ``reader`` rol MUST be rejected by the FOSTER-03 assignment
# write route (POST /casas-acogida/{id}/asignar) with 403 BEFORE the
# handler runs. The no-SQL spy doubles as the assertion that nothing in
# the handler short-circuits past the writer dep.
# ---------------------------------------------------------------------------


async def test_asignar_submit_rejects_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
) -> None:
    """Reader cannot POST an assignment (issue #144).

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
        "/casas-acogida/casa-123/asignar",
        form_data={
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "motivo": "",
        },
    )

    assert response.status_code == 403, (
        f"reader POST /casas-acogida/casa-123/asignar MUST be 403; "
        f"got {response.status_code}"
    )
    # Defense in depth: ensure the JSON error carries the writer
    # rejection message — if a future refactor swaps the dep and the
    # message drifts, the test catches it.
    assert "Permisos insuficientes" in response.text, (
        f"reader 403 response MUST carry 'Permisos insuficientes'; "
        f"got body: {response.text!r}"
    )


# ---------------------------------------------------------------------------
# FOSTER-03 (#45): ``GET /casas-acogida/{id}/overrides`` is developer-only.
# The ``motivo`` column is free text from the operator and may carry PII;
# the audit log is restricted to ``rol == "developer"`` via
# :func:`require_developer_user`. Key_user (the typical operator) still
# triggers overrides via ``/asignar`` — only the audit listing is locked.
# ---------------------------------------------------------------------------


async def test_overrides_list_requires_developer_role(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Key_user (and admin) hitting ``/overrides`` MUST be 403.

    Uses ``_login_as_key_user`` so the cookie + revalidation rol line up.
    The override SQL lookup is patched to a sentinel that records every
    call — if the route ever short-circuits past the developer dep, the
    sentinel leaks into the response body and the test fails loud.
    """
    leaked: list[Any] = []
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "list_overrides_for_casa",
        lambda _c, _cid: leaked.append(_cid) or ["SHOULD-NOT-LEAK"],
    )

    _login_as_key_user(client)

    response = await client.get("/casas-acogida/casa-123/overrides")

    assert response.status_code == 403, (
        f"key_user GET /overrides MUST be 403; got {response.status_code}"
    )
    assert leaked == [], (
        f"key_user MUST NOT trigger list_overrides_for_casa; calls: {leaked!r}"
    )
    assert "SHOULD-NOT-LEAK" not in response.text


async def test_overrides_list_allows_developer_role(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Developer hitting ``/overrides`` MUST see the audit log rows.

    Flips ``auth_reval_rol = "developer"`` BEFORE
    :func:`_login_as_developer` so the per-request revalidation SELECT
    echoes the cookie's rol. Patches the override lookup with one row
    carrying a sentinel motivo so the assertion can pin the
    developer-only render.
    """
    route_client.auth_reval_rol = "developer"
    _login_as_developer(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "list_overrides_for_casa",
        lambda _c, _cid: [_override_row(motivo="dev-only PII marker")],
    )

    response = await client.get("/casas-acogida/casa-123/overrides")

    assert response.status_code == 200
    assert "dev-only PII marker" in response.text
