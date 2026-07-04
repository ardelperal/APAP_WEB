"""Route-level tests for INTAKE-02 batch entradas.

Mirrors ``tests/test_entradas_routes.py``: routes are pure HTTP/auth/
template glue. The fixture ``_NoSqlRouteClient`` enforces the AGENTS.md
layer-boundary rule (no ``client.execute_sql`` in routes). All data
access goes through ``app.modules.entradas.batch_service``.

Coverage:
- Auth guard on every batch endpoint (5 routes).
- Form rendering of /entradas/batch/new (5 blank rows + csrf token).
- Stage POST with valid records redirects to preview.
- Stage POST with cross-batch duplicate re-renders form with 422.
- Commit POST happy path redirects to /entradas.
- Commit POST on conflict re-renders preview with 409 + error overlay.
- Cancel POST redirects to /entradas/batch/new.
- 404 on unknown batch_id.
- No SQL executed directly by routes.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.auth_dependencies import get_insforge_client_dep
from app.core.config import get_settings
from app.core.insforge import InsForgeClient
from app.core.session import session_cookie_name, write_session
from app.main import app, get_insforge_client
from app.modules.entradas import batch_service
from tests.conftest import make_csrf_request


class _NoSqlRouteClient(InsForgeClient):
    """Client spy that fails if a route executes SQL directly."""

    def __init__(self) -> None:  # type: ignore[override]
        import httpx as _httpx

        self._client = _httpx.Client(base_url="https://spy.example")

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[override]
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
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "test-csrf-token-batch",
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _valid_batch_records() -> dict[str, list[str]]:
    return {
        "animal_id": [
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        ],
        "voluntario_entrada_id": ["", ""],
        "fecha_entrada": ["2026-07-15", "2026-07-16"],
        "origen": ["Albergue", "Albergue"],
        "motivo": ["Rescate", "Rescate"],
        "observaciones": ["", ""],
    }


# --- Auth guards ----------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/entradas/batch/new"),
        ("GET", "/entradas/batch/some-id"),
        ("POST", "/entradas/batch"),
        ("POST", "/entradas/batch/some-id/commit"),
        ("POST", "/entradas/batch/some-id/cancel"),
    ],
)
async def test_batch_routes_require_authorized_user(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


# --- /entradas/batch/new (GET) ------------------------------------------


async def test_batch_new_renders_form_with_five_blank_rows_and_csrf(
    client: httpx.AsyncClient, route_client: _NoSqlRouteClient
) -> None:
    _login_as_key_user(client)
    response = await client.get("/entradas/batch/new")

    assert response.status_code == 200
    body = response.text
    assert "Entradas en lote" in body
    # 5 rows = 5 inputs named "animal_id"
    assert body.count('name="animal_id"') == 5
    assert body.count('name="fecha_entrada"') == 5
    assert body.count('name="csrf_token"') >= 1


# --- /entradas/batch (POST) stage happy path -----------------------------


async def test_batch_post_valid_records_stages_and_redirects_to_preview(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    fake_staging = batch_service.BatchStaging(
        batch_id="batch-abc",
        created_at=None,
        records=(),
    )

    def _fake_stage(client_arg: InsForgeClient, records: list[dict[str, Any]]):
        return fake_staging

    monkeypatch.setattr(batch_service, "stage_batch", _fake_stage)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/batch",
        form_data=_valid_batch_records(),
        csrf_token="test-csrf-token-batch",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/entradas/batch/batch-abc"


async def test_batch_post_cross_batch_duplicate_rerenders_form_with_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    def _fake_stage(client_arg: InsForgeClient, records: list[dict[str, Any]]):
        raise batch_service.BatchValidationError(
            "Animal duplicado en el lote: "
            "animal_id=00000000-0000-0000-0000-000000000001 fecha_entrada=2026-07-15"
        )

    monkeypatch.setattr(batch_service, "stage_batch", _fake_stage)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/batch",
        form_data=_valid_batch_records(),
        csrf_token="test-csrf-token-batch",
    )

    assert response.status_code == 422
    body = response.text
    assert "Animal duplicado en el lote" in body
    # operator input is preserved so they can fix it without retyping
    assert "00000000-0000-0000-0000-000000000001" in body


async def test_batch_post_empty_form_rerenders_with_422(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/batch",
        form_data={k: [""] for k in _valid_batch_records()},
        csrf_token="test-csrf-token-batch",
    )

    assert response.status_code == 422
    assert "A\u00f1ade al menos una entrada antes de previsualizar" in response.text
    # No service call should happen for an empty form.
    # ``monkeypatch`` is intentionally absent here.


# --- /entradas/batch/{batch_id} (GET) preview ----------------------------


async def test_batch_preview_returns_404_when_batch_unknown(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    def _fake_get(client_arg: InsForgeClient, batch_id: str):
        return None

    monkeypatch.setattr(batch_service, "get_batch", _fake_get)

    response = await client.get("/entradas/batch/missing-id")
    assert response.status_code == 404


async def test_batch_preview_renders_table_with_status_per_record(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    fake_staging = batch_service.BatchStaging(
        batch_id="batch-xyz",
        created_at="2026-07-04T10:00:00Z",
        records=(
            batch_service.BatchRecord(
                sequence=1,
                params={
                    "animal_id": "00000000-0000-0000-0000-000000000001",
                    "voluntario_entrada_id": None,
                    "fecha_entrada": "2026-07-15",
                    "origen": "Albergue",
                    "motivo": "Rescate",
                    "observaciones": None,
                },
                status="valid",
                error=None,
            ),
            batch_service.BatchRecord(
                sequence=2,
                params={
                    "animal_id": "00000000-0000-0000-0000-000000999999",
                    "voluntario_entrada_id": None,
                    "fecha_entrada": "2026-07-16",
                    "origen": "Albergue",
                    "motivo": "Rescate",
                    "observaciones": None,
                },
                status="invalid",
                error="animal_id no existe",
            ),
        ),
    )

    monkeypatch.setattr(
        batch_service, "get_batch", lambda _c, _b: fake_staging
    )

    response = await client.get("/entradas/batch/batch-xyz")

    assert response.status_code == 200
    body = response.text
    assert "Previsualizaci\u00f3n del lote" in body
    assert "V\u00e1lida" in body
    assert "animal_id no existe" in body
    assert body.count('action="/entradas/batch/batch-xyz/commit"') == 1
    assert body.count('action="/entradas/batch/batch-xyz/cancel"') == 1


# --- /entradas/batch/{batch_id}/commit (POST) ---------------------------


async def test_batch_commit_happy_path_redirects_to_entradas(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    # commit_batch returns a non-empty list on the happy path; the
    # route uses the length to decide redirect-vs-404.
    committed_entrada = batch_service.Entrada(
        id="ent-1",
        animal_id="00000000-0000-0000-0000-000000000001",
        voluntario_entrada_id=None,
        fecha_entrada="2026-07-15",
        origen="Albergue",
        motivo="Rescate",
        observaciones=None,
    )
    monkeypatch.setattr(
        batch_service, "commit_batch", lambda _c, _b: [committed_entrada]
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/batch/batch-1/commit",
        csrf_token="test-csrf-token-batch",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/entradas"


async def test_batch_commit_conflict_rerenders_preview_with_409(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    def _fake_commit(client_arg: InsForgeClient, batch_id: str):
        raise batch_service.EntradaConflictError(
            "entrada duplicada durante el commit del lote"
        )

    monkeypatch.setattr(batch_service, "commit_batch", _fake_commit)

    fake_staging = batch_service.BatchStaging(
        batch_id="batch-conflict",
        created_at=None,
        records=(
            batch_service.BatchRecord(
                sequence=1,
                params={
                    "animal_id": "00000000-0000-0000-0000-000000000001",
                    "voluntario_entrada_id": None,
                    "fecha_entrada": "2026-07-15",
                    "origen": "Albergue",
                    "motivo": "Rescate",
                    "observaciones": None,
                },
                status="valid",
                error=None,
            ),
        ),
    )
    monkeypatch.setattr(
        batch_service, "get_batch", lambda _c, _b: fake_staging
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/batch/batch-conflict/commit",
        csrf_token="test-csrf-token-batch",
    )

    assert response.status_code == 409
    body = response.text
    assert "Conflicto durante el commit" in body
    # Preview is preserved so the operator can see which record collided.
    assert "Previsualizaci\u00f3n del lote" in body


async def test_batch_commit_returns_404_when_batch_gone(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    def _fake_commit(client_arg: InsForgeClient, batch_id: str):
        raise batch_service.EntradaConflictError("entrada duplicada")

    monkeypatch.setattr(batch_service, "commit_batch", _fake_commit)
    monkeypatch.setattr(batch_service, "get_batch", lambda _c, _b: None)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/batch/missing/commit",
        csrf_token="test-csrf-token-batch",
    )

    assert response.status_code == 404


# --- /entradas/batch/{batch_id}/cancel (POST) ---------------------------


async def test_batch_cancel_redirects_to_batch_new(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login_as_key_user(client)

    monkeypatch.setattr(batch_service, "cancel_batch", lambda _c, _b: None)

    response = await make_csrf_request(
        client,
        "POST",
        "/entradas/batch/batch-cancel/cancel",
        csrf_token="test-csrf-token-batch",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/entradas/batch/new"
