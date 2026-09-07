"""Route-level tests for the minimal entradas CRUD slice."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.core.di.local_postgres_di import get_local_postgres_executor_dep
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app
from app.modules.entradas import service as entradas_service
from tests.conftest import auth_reval_rows, make_csrf_request


class _NoSqlRouteClient(LocalPostgresExecutor):
    """Client spy that fails if a route executes SQL directly."""

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
    app.dependency_overrides[get_local_postgres_executor_dep] = lambda: spy
    app.dependency_overrides[get_local_postgres_executor_dep] = lambda: spy
    yield spy
    app.dependency_overrides.pop(get_local_postgres_executor_dep, None)
    app.dependency_overrides.pop(get_local_postgres_executor_dep, None)


@pytest.fixture
def entrada() -> entradas_service.Entrada:
    return entradas_service.Entrada(
        id="ent-123",
        animal_id="animal-123",
        voluntario_entrada_id="vol-123",
        fecha_entrada="2026-06-25",
        origen="Rescate",
        motivo="Abandono",
        observaciones="Llegó tranquila",
    )


def _login_as_key_user(client: httpx.AsyncClient) -> None:
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            # PR-5B2: session-bound CSRF token.
            "csrf_token": "test-csrf-token-entradas",
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
            "csrf_token": "test-csrf-token-entradas",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _form_data(**overrides: str) -> dict[str, str]:
    data = {
        "animal_id": "animal-123",
        "voluntario_entrada_id": "vol-123",
        "fecha_entrada": "2026-06-25",
        "origen": "Rescate",
        "motivo": "Abandono",
        "observaciones": "Llegó tranquila",
    }
    data.update(overrides)
    return data


async def test_entradas_routes_require_authorized_user(client: httpx.AsyncClient) -> None:
    response = await client.get("/entradas", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"


async def test_list_entradas_delegates_to_service_and_renders_spanish_copy(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    entrada: entradas_service.Entrada,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    calls: list[LocalPostgresExecutor] = []
    monkeypatch.setattr(
        entradas_service,
        "list_entradas",
        lambda service_client: calls.append(service_client) or [entrada],
    )

    response = await client.get("/entradas")

    assert response.status_code == 200
    assert calls == [route_client]
    assert "Entradas" in response.text
    assert "Nueva entrada" in response.text
    assert "Rescate" in response.text


async def test_create_form_posts_to_create_route(client: httpx.AsyncClient) -> None:
    _login_as_key_user(client)

    response = await client.get("/entradas/new")

    assert response.status_code == 200
    assert '<form method="post" action="/entradas"' in response.text


async def test_edit_form_posts_to_update_route(
    client: httpx.AsyncClient,
    entrada: entradas_service.Entrada,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    monkeypatch.setattr(entradas_service, "get_entrada_by_id", lambda _c, _id: entrada)

    response = await client.get("/entradas/ent-123/edit")

    assert response.status_code == 200
    assert '<form method="post" action="/entradas/ent-123/update"' in response.text


async def test_detail_and_edit_return_404_when_service_returns_none(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    calls: list[tuple[LocalPostgresExecutor, str]] = []

    def fake_get(service_client: LocalPostgresExecutor, entrada_id: str):
        calls.append((service_client, entrada_id))
        return None

    monkeypatch.setattr(entradas_service, "get_entrada_by_id", fake_get)

    detail = await client.get("/entradas/missing")
    edit = await client.get("/entradas/missing/edit")

    assert detail.status_code == 404
    assert edit.status_code == 404
    assert calls == [(route_client, "missing"), (route_client, "missing")]


async def test_create_entrada_delegates_to_service_and_redirects_to_detail(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    entrada: entradas_service.Entrada,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    calls: list[tuple[LocalPostgresExecutor, dict[str, Any]]] = []

    def fake_create(service_client: LocalPostgresExecutor, params: dict[str, Any]):
        calls.append((service_client, params))
        return entrada

    monkeypatch.setattr(entradas_service, "create_entrada", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas",
        form_data=_form_data(),
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/entradas/ent-123"
    assert calls == [(route_client, _form_data())]


async def test_create_duplicate_translates_to_409_html(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    route_client: _NoSqlRouteClient,
) -> None:
    _login_as_key_user(client)

    def fake_create(service_client: LocalPostgresExecutor, params: dict[str, Any]):
        assert service_client is route_client
        raise entradas_service.EntradaConflictError("duplicada")

    monkeypatch.setattr(entradas_service, "create_entrada", fake_create)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas",
        form_data=_form_data(),
    )

    assert response.status_code == 409
    assert "No se pudo guardar la entrada" in response.text
    assert "Ya existe una entrada" in response.text


async def test_update_validation_error_rerenders_form_with_422(
    client: httpx.AsyncClient,
    entrada: entradas_service.Entrada,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    monkeypatch.setattr(entradas_service, "get_entrada_by_id", lambda _c, _id: entrada)

    def fake_update(service_client: LocalPostgresExecutor, entrada_id: str, params: dict[str, Any]):
        raise ValueError("animal_id is required and cannot be empty")

    monkeypatch.setattr(entradas_service, "update_entrada", fake_update)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/ent-123/update",
        form_data=_form_data(animal_id="   "),
    )

    assert response.status_code == 422
    assert "No se pudo guardar la entrada" in response.text
    assert "animal_id is required" in response.text


async def test_update_missing_entry_returns_404(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    monkeypatch.setattr(entradas_service, "update_entrada", lambda _c, _id, _p: None)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/missing/update",
        form_data=_form_data(),
    )

    assert response.status_code == 404


async def test_delete_is_soft_delete_service_delegation_and_redirect(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    calls: list[tuple[LocalPostgresExecutor, str]] = []

    def fake_delete(service_client: LocalPostgresExecutor, entrada_id: str) -> bool:
        calls.append((service_client, entrada_id))
        return True

    monkeypatch.setattr(entradas_service, "delete_entrada", fake_delete)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/ent-123/delete",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/entradas"
    assert calls == [(route_client, "ent-123")]


async def test_delete_missing_entry_returns_404(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)
    monkeypatch.setattr(entradas_service, "delete_entrada", lambda _c, _id: False)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/missing/delete",
    )

    assert response.status_code == 404


def test_entradas_route_source_contains_no_direct_execute_sql() -> None:
    route_source = Path("app/modules/entradas/routes.py")

    assert route_source.exists()
    assert ".execute_sql(" not in route_source.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Issue #144: a ``reader`` rol MUST be rejected by the 3 entradas write
# routes (create / update / delete) with 403 BEFORE the handler runs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,form_data",
    [
        ("POST", "/entradas", _form_data()),
        ("POST", "/entradas/ent-123/update", _form_data()),
        ("POST", "/entradas/ent-123/delete", None),
    ],
    ids=["create", "update", "delete"],
)
async def test_entradas_write_routes_reject_reader_with_403(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    method: str,
    path: str,
    form_data: dict[str, str] | None,
) -> None:
    """Reader cannot POST on any entradas write route (issue #144).

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
