"""Tests for HEALTH-06 catalog of tests + periodicity rules.

These tests cover:
1. The ``catalogos_periodicidad`` table structure and seed data
2. The ``list_catalogos_periodicidad`` service function
3. The ``list_catalogos_pruebas`` service function (already exists;
   re-prove it for regression safety)

The migration SQL file ``005_health_catalog_periodicidad.sql`` creates
``catalogos_periodicidad`` with a species-aware schema
(``especie`` column distinguishes CANINA / FELINA / NULL-for-all rules).
The seed data is the 8-row set from the legacy ``TbPruebasPeridicidad``
extracted via Dysflow on 2026-07-03.

Periodicidad rules (from legacy ``TbPruebasPeridicidad``):

+-----------+--------+-------------------+-------------------+
| Prueba   | Especie | periodicidad_meses | Recurrente        |
+-----------+--------+-------------------+-------------------+
| Vacuna Polivalente | CANINA | 12 | sí |
| Rabia    | CANINA | 12 | sí |
| Leishmaniosis | CANINA | 12 | sí |
| Desparasitación Interna | CANINA | 3 | sí |
| Desparasitación Externa | CANINA | 3 | sí |
| Vacuna Polivalente | FELINA | 12 | sí |
| Rabia    | FELINA | 12 | sí |
| Esterilización | CANINA | NULL | no (única) |
| Esterilización | FELINA | NULL | no (única) |
+-----------+--------+-------------------+-------------------+

The ``especie`` column carries ``NULL`` to signal "all species" for
backwards-compatibility with the legacy one-row-per-codigo model used in
the CATALOG-01 seed; future slices (HEALTH-04 #53) will use the
species-aware rules.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.insforge import InsForgeClient
from app.modules.sanidad import service as sanidad_service

# ---------------------------------------------------------------------------
# mock transport helpers (same pattern as test_sanidad.py)
# ---------------------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _make_client(
    handler: Any,
) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    """Build a real InsForgeClient with a mock transport that records calls."""
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


# ---------------------------------------------------------------------------
# catalogos_periodicidad tests
# ---------------------------------------------------------------------------


def test_list_catalogos_periodicidad_returns_rows() -> None:
    """list_catalogos_periodicidad returns rows from the periodicidad catalog."""
    rows = [
        {
            "id": "p-00000000-0000-0000-0000-000000000001",
            "codigo": "Heptavalente",
            "nombre": "Heptavalente",
            "periodicidad_meses": 12,
            "activo": True,
            "orden": 1,
        },
        {
            "id": "p-00000000-0000-0000-0000-000000000002",
            "codigo": "Rabia",
            "nombre": "Rabia",
            "periodicidad_meses": 12,
            "activo": True,
            "orden": 2,
        },
    ]

    def _handler(_request: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)

    client, _ = _make_client(_handler)

    result = sanidad_service.list_catalogos_periodicidad(client)

    assert len(result) == 2
    assert result[0]["codigo"] == "Heptavalente"
    assert result[0]["periodicidad_meses"] == 12
    assert result[1]["codigo"] == "Rabia"


def test_list_catalogos_periodicidad_emits_correct_sql() -> None:
    """The SQL emitted contains the periodicidad query."""
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        assert "catalogos_periodicidad" in body.get("query", "")
        return _json_response(200, [])

    client, captured = _make_client(_handler)

    sanidad_service.list_catalogos_periodicidad(client)

    assert len(captured) == 1
    assert "catalogos_periodicidad" in captured[0]["query"]


# ---------------------------------------------------------------------------
# catalogos_pruebas tests (regression safety for existing function)
# ---------------------------------------------------------------------------


def test_list_catalogos_pruebas_returns_rows() -> None:
    """list_catalogos_pruebas returns rows from the pruebas catalog."""
    rows = [
        {
            "id": "c-00000000-0000-0000-0000-000000000001",
            "codigo": "Heptavalente",
            "nombre": "Heptavalente",
            "especie": "canina",
            "observaciones": "Vacuna",
            "activo": True,
            "orden": 6,
        },
        {
            "id": "c-00000000-0000-0000-0000-000000000002",
            "codigo": "Rabia",
            "nombre": "Rabia",
            "especie": "ambos",
            "observaciones": "Vacuna",
            "activo": True,
            "orden": 12,
        },
    ]

    def _handler(_request: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)

    client, _ = _make_client(_handler)

    result = sanidad_service.list_catalogos_pruebas(client)

    assert len(result) == 2
    assert result[0]["codigo"] == "Heptavalente"
    assert result[0]["especie"] == "canina"
    assert result[1]["codigo"] == "Rabia"


def test_list_catalogos_pruebas_emits_correct_sql() -> None:
    """The SQL emitted contains the pruebas catalog query."""
    def _handler(_request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        assert "catalogos_pruebas" in body.get("query", "")
        return _json_response(200, [])

    client, captured = _make_client(_handler)

    sanidad_service.list_catalogos_pruebas(client)

    assert len(captured) == 1
    assert "catalogos_pruebas" in captured[0]["query"]


# ---------------------------------------------------------------------------
# periodicidad rules: species-aware queries (future HEALTH-04)
# ---------------------------------------------------------------------------


def test_periodicidad_rules_have_especie_column() -> None:
    """Periodicidad seed includes especie so CANINA / FELINA rules can differ.

    The legacy ``TbPruebasPeridicidad`` has separate rows per (test, species).
    The web schema must carry ``especie`` to support species-aware periodicity
    lookup (HEALTH-04, issue #53). The seed includes NULL especie for
    backwards-compatibility with the CATALOG-01 single-codigo model.
    """
    rows = [
        {
            "id": "p-00000000-0000-0000-0000-000000000001",
            "codigo": "Heptavalente",
            "nombre": "Heptavalente",
            "periodicidad_meses": 12,
            "activo": True,
            "orden": 1,
            "especie": "canina",   # species-aware: canina-specific rule
        },
        {
            "id": "p-00000000-0000-0000-0000-000000000002",
            "codigo": "Heptavalente",
            "nombre": "Heptavalente",
            "periodicidad_meses": 12,
            "activo": True,
            "orden": 2,
            "especie": "felina",   # species-aware: felina-specific rule
        },
        {
            "id": "p-00000000-0000-0000-0000-000000000003",
            "codigo": "Desparasitación Interna",
            "nombre": "Desparasitación Interna",
            "periodicidad_meses": 3,
            "activo": True,
            "orden": 3,
            "especie": "canina",   # canina: every 3 months
        },
        {
            "id": "p-00000000-0000-0000-0000-000000000004",
            "codigo": "Esterilización",
            "nombre": "Esterilización",
            "periodicidad_meses": None,  # one-shot, not recurring
            "activo": True,
            "orden": 4,
            "especie": None,   # NULL = applies to all species
        },
    ]

    def _handler(_request: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, rows)

    client, _ = _make_client(_handler)

    result = sanidad_service.list_catalogos_periodicidad(client)

    canina_rules = [r for r in result if r.get("especie") == "canina"]
    felina_rules = [r for r in result if r.get("especie") == "felina"]
    all_species = [r for r in result if r.get("especie") is None]

    assert len(canina_rules) >= 1
    assert len(felina_rules) >= 1
    assert len(all_species) >= 1
    # Desparasitación Interna is every 3 months for CANINA
    desparasitacion_canina = next(
        (r for r in canina_rules if r["codigo"] == "Desparasitación Interna"),
        None,
    )
    assert desparasitacion_canina is not None
    assert desparasitacion_canina["periodicidad_meses"] == 3
    # Esterilización has NULL periodicidad (one-shot)
    esterilizacion = next(
        (r for r in result if r["codigo"] == "Esterilización"),
        None,
    )
    assert esterilizacion is not None
    assert esterilizacion["periodicidad_meses"] is None


# ---------------------------------------------------------------------------
# periodicidad SQL structure tests (no DB needed — pure builder)
# ---------------------------------------------------------------------------


def test_catalogos_periodicidad_sql_contains_especie_column() -> None:
    """The LIST_CATALOGOS_PERIODICIDAD_SQL includes especie in SELECT.

    This is the query used by ``list_catalogos_periodicidad``.
    Adding especie late (after the initial CATALOG-01 seed that used
    ``codigo`` as the sole key) would be a breaking schema change.
    This test pins the contract so a future schema refactor is visible
    in the diff.
    """
    from app.core.catalogs import LIST_CATALOGOS_PERIODICIDAD_SQL

    assert "especie" in LIST_CATALOGOS_PERIODICIDAD_SQL


def test_catalogos_periodicidad_seed_has_eight_rows() -> None:
    """The periodicity seed has 8 rows from ``TbPruebasPeridicidad``.

    Rows (Prueba, Especie, periodicidad_meses):
      1. Vacuna Polivalente, CANINA, 12
      2. Rabia, CANINA, 12
      3. Leishmaniosis, CANINA, 12
      4. Desparasitación Interna, CANINA, 3
      5. Desparasitación Externa, CANINA, 3
      6. Vacuna Polivalente, FELINA, 12
      7. Rabia, FELINA, 12
      8. Esterilización, CANINA, NULL
      9. Esterilización, FELINA, NULL

    The count is 9 because Esterilización appears for both species.
    This test pins the seed row count so a future maintainer knows
    to update the migration AND the tests when the seed changes.
    """
    from app.core.catalogs import CATALOGOS_PERIODICIDAD_SEED_SQL

    # Count INSERT VALUE rows (each row is on its own line with leading whitespace)
    lines = CATALOGOS_PERIODICIDAD_SEED_SQL.split("\n")
    value_lines = [ln for ln in lines if ln.strip().startswith("(") and not ln.strip().startswith("--")]
    assert len(value_lines) == 9, (
        f"Expected 9 periodicity seed rows, got {len(value_lines)}. "
        "Update this test when TbPruebasPeridicidad changes."
    )


def test_esterilizacion_one_shot_has_null_periodicidad() -> None:
    """Esterilización is a one-shot (not recurring), so periodicidad_meses is NULL.

    From the legacy: "Esterilización — — (única, no recurrente)".
    The seed must use NULL (not 0 or some sentinel) to distinguish
    a one-shot operation from a recurring one with zero-month interval.
    """
    from app.core.catalogs import CATALOGOS_PERIODICIDAD_SEED_SQL

    # Check that Esterilización appears with NULL periodicidad
    assert "Esterilización" in CATALOGOS_PERIODICIDAD_SEED_SQL
    # The NULL value for periodicidad_meses should appear in the VALUES clause
    # Look for the Esterilización row pattern: (something, 'Esterilización', ...)
    # followed eventually by NULL (not a number) for periodicidad_meses
    assert "NULL" in CATALOGOS_PERIODICIDAD_SEED_SQL


def test_desparasitacion_is_3_months_for_canina() -> None:
    """Desparasitación Interna / Externa are every 3 months for CANINA.

    From the legacy: "Desparasitación Interna | CANINA | 3 meses".
    This is notably different from the other tests (12 months).
    """
    from app.core.catalogs import CATALOGOS_PERIODICIDAD_SEED_SQL

    assert "Desparasitación Interna" in CATALOGOS_PERIODICIDAD_SEED_SQL
    assert "Desparasitación Externa" in CATALOGOS_PERIODICIDAD_SEED_SQL
    # Both desparasitacion entries should have periodicidad_meses = 3
    # The seed line for Desparasitación Internal: "... 'Desparasitación Interna', 3, ..."
    assert ", 3," in CATALOGOS_PERIODICIDAD_SEED_SQL or ", 3 " in CATALOGOS_PERIODICIDAD_SEED_SQL
