"""Integration: /asignar redirect → GET /acogidas/new prefill (issue #1008).

End-to-end over the REAL app (``app.main.create_app()`` with the full
middleware chain: auth gate → CsrfMiddleware → routes) against REAL
Postgres (real lifespan provisioning, real rows):

1. Seed an active animal, an active casa de acogida and an authorized
   key_user directly in the ephemeral schema.
2. ``POST /casas-acogida/{casa_id}/asignar`` runs the real FOSTER-03
   gate through the real ``AnimalsPort`` adapter and 303-redirects to
   ``/acogidas/new?animal_id=...&casa_acogida_id=...`` (issue #919
   encoding).
3. Following the redirect must render the create form with the
   operator's values prefilled (issue #1008 — previously ``form_data={}``
   dropped them) and, on the override branch, the hidden
   ``override_id`` threaded through (issue #142 contract).

Both gate outcomes are covered: ``admit`` (capacidad available → no
override) and ``admit_with_warning`` + motivo (capacidad 0 → override
row recorded in ``foster_capacity_overrides`` and its id echoed in the
redirect query).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from psycopg import sql

from app.core.local_backend.db import LocalPostgresExecutor
from app.core.session import session_cookie_name, write_session
from tests.integration.conftest import _require_postgres_dsn

_EMAIL = "prefill-real-app@test.com"
_CSRF = "integration-csrf-token-acogidas"


@pytest.fixture
async def prefill_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Stand up ``create_app()`` on its own ephemeral schema (real lifespan).

    Mirrors the ``real_app_harness`` pattern from
    ``tests/integration/test_magic_link_real_app.py`` (issue #917): the
    real lifespan provisions bootstrap + catalogs + domain + SQL
    migrations so animales/casas_acogida/foster_capacity_overrides all
    exist as production tables.
    """
    import uuid as uuid_module

    import psycopg

    dsn = _require_postgres_dsn()
    schema = f"prefill_{uuid_module.uuid4().hex[:10]}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    monkeypatch.setenv("APAP_LOCAL_DB_URL", dsn)
    monkeypatch.setenv("APAP_LOCAL_DB_SCHEMA", schema)
    monkeypatch.setenv(
        "APAP_SESSION_SECRET",
        "integration-test-secret-64-chars-long-padding-x",
    )

    from app.main import create_app

    app = create_app()
    try:
        async with app.router.lifespan_context(app):
            client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://testserver",
                follow_redirects=False,
            )
            try:
                yield {
                    "client": client,
                    "executor": app.state.sql_executor,
                    "secret": app.state.session_secret,
                }
            finally:
                await client.aclose()
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )


def _seed_rows(executor: LocalPostgresExecutor, capacidad: int) -> dict[str, str]:
    """Insert user + animal + casa rows; return their ids (real UUIDs)."""
    user_id = executor.execute_sql(
        "INSERT INTO usuarios_autorizados (email, rol, activo) "
        "VALUES ($1, 'key_user', true) RETURNING id",
        [_EMAIL],
    )[0]["id"]
    animal_id = executor.execute_sql(
        "INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, "
        "fnacimiento, fecha_alta, activo) "
        "VALUES ($1, 'CHIP-PREFILL-001', 'Toby', 'CANINA', 'M', '2020-01-15', "
        "now(), true) RETURNING id",
        ["11111111-1111-1111-1111-111111111111"],
    )[0]["id"]
    casa_id = executor.execute_sql(
        "INSERT INTO casas_acogida (id, nombre, apellidos, calle, telefono, "
        "localidad, provincia, coche, capacidad, activo, fecha_alta) "
        "VALUES ($1, 'Casa Prefill', 'Test', 'Calle Sol 1', '600111222', "
        "'Madrid', 'Madrid', 'No', $2, true, now()) RETURNING id",
        ["33333333-3333-3333-3333-333333333333", capacidad],
    )[0]["id"]
    return {
        "user_id": str(user_id),
        "animal_id": str(animal_id),
        "casa_id": str(casa_id),
    }


def _login(harness: dict[str, Any], user_id: str) -> None:
    """Mint a session cookie carrying the CSRF token and the actor id."""
    token = write_session(
        {
            "email": _EMAIL,
            "rol": "key_user",
            "user_id": user_id,
            "is_authorized": True,
            "csrf_token": _CSRF,
        },
        secret=harness["secret"],
    )
    harness["client"].cookies.set(session_cookie_name(), token)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_asignar_admit_redirect_prefills_new_form(
    prefill_harness: dict[str, Any],
) -> None:
    """admit → 303 → GET /acogidas/new renders the ids prefilled."""
    harness = prefill_harness
    ids = _seed_rows(harness["executor"], capacidad=1)
    _login(harness, ids["user_id"])

    redirect = await harness["client"].post(
        f"/casas-acogida/{ids['casa_id']}/asignar",
        data={"animal_id": ids["animal_id"], "csrf_token": _CSRF},
    )
    assert redirect.status_code == 303, redirect.text
    location = redirect.headers["location"]
    assert location.startswith("/acogidas/new?")
    query = parse_qs(urlsplit(location).query)
    assert query["animal_id"] == [ids["animal_id"]]
    assert query["casa_acogida_id"] == [ids["casa_id"]]
    assert "override_id" not in query

    form = await harness["client"].get(location)
    assert form.status_code == 200
    body = form.text
    assert f'name="animal_id" value="{ids["animal_id"]}"' in body
    assert f'name="casa_acogida_id" value="{ids["casa_id"]}"' in body
    assert 'name="override_id"' not in body


@pytest.mark.integration
@pytest.mark.asyncio
async def test_asignar_override_redirect_threads_hidden_override_id(
    prefill_harness: dict[str, Any],
) -> None:
    """admit_with_warning + motivo → override id threaded into the form.

    The casa's capacity is genuinely exhausted by a REAL active estancia
    row (``capacidad >= 1`` is a DB check constraint, so capacity excess
    is produced with data, not with ``capacidad=0``). The override row really lands in ``foster_capacity_overrides`` and
    its DB-minted id reaches the hidden form field via the redirect
    query (issue #142 contract, now consumed downstream per #1008).
    """
    harness = prefill_harness
    ids = _seed_rows(harness["executor"], capacidad=1)
    # Exhaust the casa's capacity with a real open estancia (capacidad=1
    # is the DB floor; the check constraint forbids capacidad=0).
    harness["executor"].execute_sql(
        "INSERT INTO acogidas (id, animal_id, casa_acogida_id, fecha_inicio) "
        "VALUES ($1, $2, $3, '2026-09-01')",
        ["22222222-2222-2222-2222-222222222222", ids["animal_id"], ids["casa_id"]],
    )
    _login(harness, ids["user_id"])

    redirect = await harness["client"].post(
        f"/casas-acogida/{ids['casa_id']}/asignar",
        data={
            "animal_id": ids["animal_id"],
            "motivo": "casa amplia, capacidad excedida justificada",
            "csrf_token": _CSRF,
        },
    )
    assert redirect.status_code == 303, redirect.text
    query = parse_qs(urlsplit(redirect.headers["location"]).query)
    override_id = query["override_id"][0]

    rows = harness["executor"].execute_sql(
        "SELECT id, casa_acogida_id, animal_id, estancia_id FROM "
        "foster_capacity_overrides WHERE id = $1",
        [override_id],
    )
    assert len(rows) == 1
    assert rows[0]["estancia_id"] is None  # not yet linked to a stay

    form = await harness["client"].get(redirect.headers["location"])
    assert form.status_code == 200
    assert f'name="override_id" value="{override_id}"' in form.text
    assert f'name="animal_id" value="{ids["animal_id"]}"' in form.text
    assert f'name="casa_acogida_id" value="{ids["casa_id"]}"' in form.text
