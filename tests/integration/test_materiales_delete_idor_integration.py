"""Route-level IDOR integration tests for the materiales delete endpoint.

Issue #919 (finding A-07 of audit epic #911): ``POST
/acogidas/{estancia_id}/materiales/{junction_id}/delete`` must only
deactivate a junction row that belongs to ``estancia_id``. Before the
fix, the handler deleted whatever ``junction_id`` it received and used
``estancia_id`` only for the redirect — a partial IDOR.

These tests run against REAL Postgres (the integration conftest's
ephemeral schema with the full domain provisioning): the route is
driven through the ASGI app with the production
``LocalBackendMaterialesAdapter`` over a ``LocalPostgresExecutor``
bound to the ephemeral schema, so the actual UPDATE statement is what
gets exercised — not a stub.

Acceptance criteria (issue #919):

- Deleting a junction of estancia B through estancia A's URL -> 404
  and the row stays active (fail closed).
- The legitimate delete (junction owned by the URL's estancia) keeps
  working: 303 + row deactivated.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.core.auth_dependencies import get_local_postgres_executor_dep
from app.core.config import get_settings
from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from app.main import app, get_local_backend_client
from app.modules.materiales import queries as materiales_queries
from app.modules.materiales.adapters.local_backend.materiales_local_backend_adapter import (
    LocalBackendMaterialesAdapter,
)
from app.modules.materiales.di import get_materiales_port
from tests.conftest import make_csrf_request
from tests.integration.conftest import _EphemeralPostgres

_EMAIL = "idor-materiales@example.com"
_CSRF_TOKEN = "test-csrf-token-idor-materiales"


@pytest.fixture
def real_materiales_app(
    ephemeral_postgres: _EphemeralPostgres,
    self_host_schema: _EphemeralPostgres,
    schema_postgres_dsn: str,
) -> LocalPostgresExecutor:
    """Bind the real production executor + adapter to the ephemeral schema.

    Creates the auth-revalidation user row (``require_authorized_user``
    SELECTs ``usuarios_autorizados`` on every request) and overrides the
    materiales port and the executor dependencies so the whole request
    flows through the production adapter against real Postgres.
    """
    executor = LocalPostgresExecutor(
        schema_postgres_dsn, search_path=ephemeral_postgres.schema
    )
    executor.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol, activo) VALUES ($1, 'key_user', true)",
        [_EMAIL],
    )
    adapter = LocalBackendMaterialesAdapter(executor)

    app.dependency_overrides[get_materiales_port] = lambda: adapter
    app.dependency_overrides[get_local_backend_client] = lambda: executor
    app.dependency_overrides[get_local_postgres_executor_dep] = lambda: executor
    try:
        yield executor
    finally:
        # Teardown every key this fixture set (mirrors the sibling
        # ``route_client`` fixture in tests/test_materiales_routes.py):
        # without it the overrides would leak into sibling tests sharing
        # the module-level ``app`` instance.
        app.dependency_overrides.pop(get_materiales_port, None)
        app.dependency_overrides.pop(get_local_backend_client, None)
        app.dependency_overrides.pop(get_local_postgres_executor_dep, None)


def _login(client: httpx.AsyncClient) -> None:
    """Mint a writer session cookie carrying the CSRF token."""
    token = write_session(
        {
            "email": _EMAIL,
            "rol": "key_user",
            "user_id": "u-idor",
            "is_authorized": True,
            "csrf_token": _CSRF_TOKEN,
        },
        secret=get_settings().session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _seed_estancia(executor: LocalPostgresExecutor) -> str:
    """Insert the minimum chain (animal, casa, acogida) and return its id.

    Uses unique values per call so each test seeds two independent
    estancias (A and B).
    """
    animal_id = str(uuid4())
    executor.execute_sql(
        "INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo)"
        " VALUES ($1, $2, 'Luna', 'CANINA', 'H', '2019-06-01', now(), true)",
        [animal_id, f"CHIP-{animal_id[:8]}"],
    )
    casa_id = str(uuid4())
    executor.execute_sql(
        "INSERT INTO casas_acogida (id, nombre, apellidos, calle, telefono, localidad, provincia, coche, capacidad, activo, fecha_alta)"
        " VALUES ($1, 'Casa IDOR', 'Test', 'Calle 1', '123456789', 'Madrid', 'Madrid', 'No', 1, true, now())",
        [casa_id],
    )
    estancia_id = str(uuid4())
    executor.execute_sql(
        "INSERT INTO acogidas (id, animal_id, fecha_inicio, direccion, telefono, activo, fecha_alta)"
        " VALUES ($1, $2, $3, 'Direccion test', '123456789', true, now())",
        [estancia_id, animal_id, date.today()],
    )
    return estancia_id


def _seed_junction(
    executor: LocalPostgresExecutor, estancia_id: str
) -> str:
    """Insert one material assigned to ``estancia_id``; return junction id."""
    material_id = str(uuid4())
    executor.execute_sql(
        "INSERT INTO materiales (id, material, tamano, color, activo, fecha_alta)"
        " VALUES ($1, 'Arena sanitaria', '10kg', 'Blanca', true, now())",
        [material_id],
    )
    sql, params = materiales_queries.build_junction_insert(
        estancia_id=estancia_id,
        material_id=material_id,
        cantidad=1,
        notas=None,
    )
    rows: list[dict[str, Any]] = executor.execute_sql(sql, params)
    return str(rows[0]["id"])


def _junction_active(executor: LocalPostgresExecutor, junction_id: str) -> bool:
    """Return the ``activo`` flag of the junction row (read-back)."""
    rows = executor.execute_sql(
        "SELECT activo FROM estancia_materiales WHERE id = $1", [junction_id]
    )
    assert len(rows) == 1
    return bool(rows[0]["activo"])


@pytest.mark.integration
async def test_delete_junction_of_other_estancia_returns_404_and_keeps_row_active(
    client: httpx.AsyncClient,
    real_materiales_app: LocalPostgresExecutor,
) -> None:
    """IDOR: junction of estancia B deleted via estancia A's URL -> 404.

    Issue #919: the handler must fail closed — no deletion, 404 — when
    the junction row does not belong to the estancia in the URL.
    """
    estancia_a = _seed_estancia(real_materiales_app)
    estancia_b = _seed_estancia(real_materiales_app)
    junction_b = _seed_junction(real_materiales_app, estancia_b)
    _login(client)

    response = await make_csrf_request(
        client,
        "POST",
        f"/acogidas/{estancia_a}/materiales/{junction_b}/delete",
        csrf_token=_CSRF_TOKEN,
    )

    assert response.status_code == 404
    assert _junction_active(real_materiales_app, junction_b) is True


@pytest.mark.integration
async def test_delete_own_junction_still_redirects_and_deactivates(
    client: httpx.AsyncClient,
    real_materiales_app: LocalPostgresExecutor,
) -> None:
    """Legitimate delete (junction owned by the URL's estancia) -> 303.

    Pins that the ownership check does not break the happy path: the
    junction row ends up deactivated and the redirect points at the
    per-estancia materiales list.
    """
    estancia_b = _seed_estancia(real_materiales_app)
    junction_b = _seed_junction(real_materiales_app, estancia_b)
    _login(client)

    response = await make_csrf_request(
        client,
        "POST",
        f"/acogidas/{estancia_b}/materiales/{junction_b}/delete",
        csrf_token=_CSRF_TOKEN,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/acogidas/{estancia_b}/materiales"
    assert _junction_active(real_materiales_app, junction_b) is False
