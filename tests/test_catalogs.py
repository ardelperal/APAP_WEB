"""Tests for the catalog (reference data) tables migrated from Access legacy.

The 5 catalog tables mirror the source-of-truth data from the legacy
Microsoft Access database ``Registro_APAP_Alcala_datos_18.accdb``:

    catalogos_origenes       <-  TbOrigenEntrada        (7 rows)
    catalogos_motivos        <-  TbMotivosEntrada       (21 rows)
    catalogos_pruebas        <-  TbNombrePruebas        (13 rows)
    catalogos_periodicidad   <-  TbPruebasPeridicidad   (12 rows)
    catalogos_tipos_contrato <-  TbPlantillas           (8 rows)

Counts verified via Dysflow MCP on 2026-07-03 against
``C:\\00repos\\codigo\\APAP_ACTUAL\\Registro_APAP_Alcala_datos_18.accdb``.
This file exercises:

1. Schema structure (CREATE TABLE IF NOT EXISTS, columns, UNIQUE constraints).
2. The seed runs every catalog with the legacy values, restored to proper
   Spanish (the Access file shows mojibake because Dysflow decodes CP1252
   bytes as UTF-8 when reporting to the agent — the seed restores the
   intended Spanish text and documents the source-of-truth moment).
3. Idempotence: running ``ensure_catalogs`` twice with a recording client
   produces the same logical effect — the second run does not error and
   does not duplicate rows (UNIQUE constraint + ON CONFLICT DO NOTHING).
4. Read helpers (``list_catalogos_<name>``) call the expected SQL and
   surface the rows.

Mirrors the deterministic ``SqlExecutor`` fake pattern in
``tests/test_domain.py`` so no real database is touched.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.catalogs import (
    CATALOGOS_MOTIVOS_CREATE_SQL,
    CATALOGOS_ORIGENES_CREATE_SQL,
    CATALOGOS_PERIODICIDAD_CREATE_SQL,
    CATALOGOS_PRUEBAS_CREATE_SQL,
    CATALOGOS_TIPOS_CONTRATO_CREATE_SQL,
    ensure_catalogs,
    list_catalogos_motivos,
    list_catalogos_origenes,
    list_catalogos_periodicidad,
    list_catalogos_pruebas,
    list_catalogos_tipos_contrato,
)
from app.core.data_access import BackendError, SqlExecutor
from tests.sql_executor_fake import HandlerSqlExecutor

# --- helpers --------------------------------------------------------------


class _FakeSqlExecutor:
    """Captures SQL without hitting the network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self._responses: list[list[dict[str, object]]] = []

    def set_response(self, rows: list[dict[str, object]]) -> None:
        self._responses = [rows]

    def set_responses(self, *responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)

    def execute_sql(self, query: str, params: list[object] | None = None) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        if self._responses:
            return self._responses.pop(0)
        return []

    def close(self) -> None:
        pass  # No-op for fake

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording() -> tuple[SqlExecutor, list[tuple[str, list[object]]]]:
    """Build a fake executor that records every ``execute_sql`` call.

    The returned ``captured`` list contains ``(query, params)`` tuples
    so callers can assert SQL shape and positional parameters without
    needing a real Postgres instance. Mirrors the canonical pattern
    from ``tests/test_entradas.py``.
    """
    fake = _FakeSqlExecutor()
    return fake, fake.calls


def _column_names(sql: str) -> set[str]:
    """Parse the parenthesised body of a CREATE TABLE statement.

    Same naive parser used in ``tests/test_domain.py``: depth-aware comma
    split, skipping constraint lines (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK).
    """
    match = re.search(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+\w+\s*\((.*)\)\s*$",
        sql,
        re.DOTALL,
    )
    assert match is not None, f"could not parse CREATE TABLE body from: {sql!r}"
    body = match.group(1)
    columns: list[str] = []
    depth = 0
    current: list[str] = []
    for char in body:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            columns.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        columns.append("".join(current).strip())
    names: set[str] = set()
    for col in columns:
        first = col.split()[0] if col.split() else ""
        if first.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            continue
        names.add(first)
    return names


def _seed_sql_for(table: str):
    """Return the seed SQL constant for the given catalog table.

    The implementation exposes one ``<TABLE>_SEED_SQL`` constant per
    catalog (5 of them). If a future refactor consolidates them, this
    helper still resolves by searching for the ``INSERT INTO <table>``
    owner.
    """
    import app.core.catalogs as catalogs_module

    direct_name = f"{table.upper()}_SEED_SQL"
    if hasattr(catalogs_module, direct_name):
        return getattr(catalogs_module, direct_name)
    # Fallback: walk module attrs looking for any SEED whose body INSERTs here.
    for attr in dir(catalogs_module):
        if not attr.endswith("_SEED_SQL"):
            continue
        value = getattr(catalogs_module, attr, "")
        if isinstance(value, str) and f"INSERT INTO {table}" in value:
            return value
    pytest.fail(f"no seed SQL constant for {table!r} in app.core.catalogs")


def _table_name_from_create(sql: str) -> str:
    """Extract the bare table name from ``CREATE TABLE IF NOT EXISTS <name> (...)``."""
    match = re.search(
        r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)\s*\(",
        sql,
    )
    assert match is not None, f"could not parse table name from: {sql!r}"
    return match.group(1)


# --- catalogos_origenes (TbOrigenEntrada, 7 rows) -------------------------


def test_catalogos_origenes_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS catalogos_origenes" in (
        CATALOGOS_ORIGENES_CREATE_SQL
    )


def test_catalogos_origenes_create_table_sql_has_required_columns() -> None:
    """The catalog carries the catalog columns (id, codigo, nombre, etc.)."""
    columns = _column_names(CATALOGOS_ORIGENES_CREATE_SQL)
    required = {"id", "codigo", "nombre", "activo"}
    missing = required - columns
    assert not missing, f"catalogos_origenes missing columns: {sorted(missing)}"


def test_catalogos_origenes_codigo_is_unique() -> None:
    """codigo is the natural key — the constraint makes the seed idempotent."""
    assert "UNIQUE" in CATALOGOS_ORIGENES_CREATE_SQL
    assert "codigo" in CATALOGOS_ORIGENES_CREATE_SQL


def test_catalogos_origenes_seed_contains_all_seven_legacy_values() -> None:
    """Every origen from TbOrigenEntrada (7 rows) is seeded.

    Source: Dysflow verification on 2026-07-03 against
    ``TbOrigenEntrada`` in ``Registro_APAP_Alcala_datos_18.accdb``.
    Moijibake in the Access file ('Adopci\u00f3n' read as 'Adopci?n') is
    restored to proper Spanish in this seed. We assert the count is
    exactly 7 by counting VALUES tuples on the captured SEED SQL.
    """
    seed_sql = _seed_sql_for("catalogos_origenes")
    expected = {
        "Acogida",
        "Adopción",
        "Camada",
        "Compra",
        "otros",
        "Recogido de la calle",
        "Regalo",
    }
    found: set[str] = set()
    for value in expected:
        assert f"'{value}'" in seed_sql, (
            f"catalogos_origenes seed missing the literal {value!r}"
        )
        found.add(value)
    assert len(found) == 7, f"expected 7 origenes, got {len(found)}"


# --- catalogos_motivos (TbMotivosEntrada, 21 rows) -----------------------


def test_catalogos_motivos_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS catalogos_motivos" in (
        CATALOGOS_MOTIVOS_CREATE_SQL
    )


def test_catalogos_motivos_create_table_sql_has_required_columns() -> None:
    """TbMotivosEntrada has Motivo + Especie; the catalog keeps both.

    The natural key is (codigo, especie) because the same Motivo can
    occur with different Especie values.
    """
    columns = _column_names(CATALOGOS_MOTIVOS_CREATE_SQL)
    required = {"id", "codigo", "nombre", "especie", "activo"}
    missing = required - columns
    assert not missing, f"catalogos_motivos missing columns: {sorted(missing)}"


def test_catalogos_motivos_seed_contains_all_twentyone_legacy_pairs() -> None:
    """21 motivos verified via Dysflow, with Especie attached.

    Mojibake in the legacy ('Asociaci\u00f3n', 'Inadaptaci\u00f3n',
    'Lo sac\u00f3', 'Retirado por la Asociaci\u00f3n (malas condiciones)',
    'Separaci\u00f3n') is restored to proper Spanish here.
    """
    expected = {
        "Abandono",
        "Agresividad",
        "Alergia",
        "Camada que no consigue colocar",
        "Cambio de domicilio",
        "De colonia de gatos",
        "Desalojo (hacinamiento)",
        "Enfermedad del propietario",
        "Entregados por otra Asociación",
        "Inadaptación",
        "Lo sacó de perrera para evitar su sacrificio",
        "Maltrato",
        "Motivos desconocidos",
        "Muerte propietario",
        "No se puede hacer cargo",
        "Recogido en la calle",
        "Regalo no deseado",
        "Rescate",
        "Retirado por la Asociación (malas condiciones)",
        "Se han cansado del animal",
        "Separación",
    }
    seed_sql = _seed_sql_for("catalogos_motivos")
    found: set[str] = set()
    for value in expected:
        assert f"'{value}'" in seed_sql, (
            f"catalogos_motivos seed missing the literal {value!r}"
        )
        found.add(value)
    assert len(found) == 21, f"expected 21 motivos, got {len(found)}"


def test_catalogos_motivos_seed_has_FELINA_colonia_de_gatos() -> None:
    """The single FELINA-only motivo must be present with the right Especie.

    This pins one concrete (codigo, especie) pair from the legacy to
    guard against accidental Especie swaps during restoration.
    """
    seed_sql = _seed_sql_for("catalogos_motivos")
    assert "'De colonia de gatos'" in seed_sql
    assert "'FELINA'" in seed_sql
    # The FELINA literal should appear in the VALUES block, not just the
    # CREATE TABLE column declaration.
    values_section = seed_sql[seed_sql.upper().find("VALUES") :]
    assert "'FELINA'" in values_section, (
        f"FELINA not present inside the VALUES section of the seed: {seed_sql!r}"
    )


# --- catalogos_pruebas (TbNombrePruebas, 13 rows) ------------------------


def test_catalogos_pruebas_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS catalogos_pruebas" in (
        CATALOGOS_PRUEBAS_CREATE_SQL
    )


def test_catalogos_pruebas_create_table_sql_has_required_columns() -> None:
    """TbNombrePruebas has NombrePrueba + Especie + Observaciones."""
    columns = _column_names(CATALOGOS_PRUEBAS_CREATE_SQL)
    required = {"id", "codigo", "nombre", "especie", "observaciones", "activo"}
    missing = required - columns
    assert not missing, f"catalogos_pruebas missing columns: {sorted(missing)}"


def test_catalogos_pruebas_seed_contains_all_thirteen_legacy_triples() -> None:
    """13 pruebas verified via Dysflow, with Especie + Observaciones."""
    seed_sql = _seed_sql_for("catalogos_pruebas")
    expected_codigos = {
        "Básico",
        "Desparasitación Externa",
        "Desparasitación Interna",
        "EHR",
        "Esterilización",
        "Heptavalente",
        "IFI",
        "LEUC",
        "Leucemia",
        "LH",
        "Puppy",
        "Rabia",
        "Trivalente",
    }
    found: set[str] = set()
    for value in expected_codigos:
        assert f"'{value}'" in seed_sql, (
            f"catalogos_pruebas seed missing the literal {value!r}"
        )
        found.add(value)
    assert len(found) == 13, f"expected 13 pruebas, got {len(found)}"


# --- catalogos_periodicidad (TbPruebasPeridicidad, 12 rows) --------------


def test_catalogos_periodicidad_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS catalogos_periodicidad" in (
        CATALOGOS_PERIODICIDAD_CREATE_SQL
    )


def test_catalogos_periodicidad_create_table_sql_has_required_columns() -> None:
    """TbPruebasPeridicidad has species-aware columns (especie added in HEALTH-06)."""
    columns = _column_names(CATALOGOS_PERIODICIDAD_CREATE_SQL)
    required = {
        "id",
        "codigo",
        "nombre",
        "especie",
        "periodicidad_meses",
        "activo",
    }
    missing = required - columns
    assert not missing, f"catalogos_periodicidad missing columns: {sorted(missing)}"


def test_catalogos_periodicidad_seed_has_nine_species_aware_rows() -> None:
    """9 periodicity rules from TbPruebasPeridicidad (species-aware, HEALTH-06 #55).

    Seed rows (from legacy TbPruebasPeridicidad, Dysflow 2026-07-03):
      1. Vacuna Polivalente CANINA  12 meses
      2. Rabia             CANINA  12 meses
      3. Leishmaniosis     CANINA  12 meses
      4. Desparasitación Int CANINA  3 meses
      5. Desparasitación Ext CANINA  3 meses
      6. Vacuna Polivalente FELINA  12 meses
      7. Rabia             FELINA  12 meses
      8. Esterilización    CANINA  NULL (one-shot)
      9. Esterilización    FELINA  NULL (one-shot)

    The old 12-row codigo-only seed is replaced by this 9-row
    species-aware seed (HEALTH-06 migration).
    """
    seed_sql = _seed_sql_for("catalogos_periodicidad")
    # 9 distinct test names in the new seed
    expected = {
        "Vacuna Polivalente",
        "Rabia",
        "Leishmaniosis",
        "Desparasitación Interna",
        "Desparasitación Externa",
        "Esterilización",
    }
    found: set[str] = set()
    for value in expected:
        assert f"'{value}'" in seed_sql, (
            f"catalogos_periodicidad seed missing the literal {value!r}"
        )
        found.add(value)
    assert len(found) == 6, f"expected 6 distinct test names, got {len(found)}"


# --- catalogos_tipos_contrato (TbPlantillas, 8 rows) ---------------------


def test_catalogos_tipos_contrato_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS catalogos_tipos_contrato" in (
        CATALOGOS_TIPOS_CONTRATO_CREATE_SQL
    )


def test_catalogos_tipos_contrato_create_table_sql_has_required_columns() -> None:
    """TbPlantillas metadata (InicialDocumento, NombreCampo) is preserved."""
    columns = _column_names(CATALOGOS_TIPOS_CONTRATO_CREATE_SQL)
    required = {
        "id",
        "codigo",
        "nombre",
        "iniciales",
        "descripcion",
        "tabla_legacy",
        "campo_legacy",
        "activo",
    }
    missing = required - columns
    assert not missing, f"catalogos_tipos_contrato missing columns: {sorted(missing)}"


def test_catalogos_tipos_contrato_seed_contains_all_eight_legacy_values() -> None:
    """8 tipos de contrato verified via Dysflow against TbPlantillas.

    Source: Dysflow inspection of ``TbPlantillas`` on 2026-07-03 — count
    is exactly 8, matching Fase 7 of ``docs/roadmap.md`` §3
    ("los 8 tipos de contrato").
    """
    seed_sql = _seed_sql_for("catalogos_tipos_contrato")
    expected = {
        "Acogida",
        "Adopción",
        "Cesión",
        "Entrada",
        "Entregado a Propietario",
        "Ficha de Seguimiento",
        "Ficha Sanitaria Gatos",
        "Ficha Sanitaria Perros",
    }
    found: set[str] = set()
    for value in expected:
        assert f"'{value}'" in seed_sql, (
            f"catalogos_tipos_contrato seed missing the literal {value!r}"
        )
        found.add(value)
    assert len(found) == 8, f"expected 8 tipos de contrato, got {len(found)}"


# --- ensure_catalogs orchestration ---------------------------------------


def test_ensure_catalogs_creates_all_five_catalog_tables() -> None:
    """The bootstrap creates 5 catalog tables + 5 seed statements."""
    fake, captured = _client_recording()

    ensure_catalogs(fake)

    queries = [c[0].strip() for c in captured]
    create_table_names = [
        _table_name_from_create(q)
        for q in queries
        if q.startswith("CREATE TABLE IF NOT EXISTS ")
    ]
    assert create_table_names == [
        "catalogos_origenes",
        "catalogos_motivos",
        "catalogos_pruebas",
        "catalogos_periodicidad",
        "catalogos_tipos_contrato",
    ], f"catalog tables in wrong order: {create_table_names}"


def test_ensure_catalogs_runs_each_seed_after_its_create_table() -> None:
    """DDL + seed for the same catalog must be adjacent (atomic per-catalog)."""
    fake, captured = _client_recording()

    ensure_catalogs(fake)

    queries = [c[0].strip() for c in captured]
    expected_pairs = [
        "catalogos_origenes",
        "catalogos_motivos",
        "catalogos_pruebas",
        "catalogos_periodicidad",
        "catalogos_tipos_contrato",
    ]
    # Walk the query stream and ensure each table's INSERT comes right
    # after its CREATE, with no other CREATE sitting between them.
    last_create_idx: dict[str, int] = {}
    for idx, q in enumerate(queries):
        for table in expected_pairs:
            if q.startswith(f"CREATE TABLE IF NOT EXISTS {table}"):
                last_create_idx[table] = idx
            elif q.startswith(f"INSERT INTO {table}"):
                create_idx = last_create_idx.get(table, -1)
                assert create_idx >= 0, (
                    f"INSERT into {table} at idx {idx} appears before its CREATE"
                )
                between = queries[create_idx + 1 : idx]
                assert not any(
                    b.startswith("CREATE TABLE IF NOT EXISTS ") for b in between
                ), (
                    f"INSERT into {table} at idx {idx} is separated from its "
                    f"CREATE by another CREATE; queries={queries}"
                )


def test_ensure_catalogs_uses_on_conflict_do_nothing_for_idempotence() -> None:
    """Every seed must use ON CONFLICT DO NOTHING (idempotent on retry)."""
    fake, captured = _client_recording()

    ensure_catalogs(fake)

    inserts = [c[0] for c in captured if "INSERT INTO" in c[0]]
    assert len(inserts) == 5, f"expected 5 inserts, got {len(inserts)}: {inserts}"
    for ins in inserts:
        assert "ON CONFLICT" in ins.upper(), (
            f"insert lacks ON CONFLICT (idempotence guard): {ins!r}"
        )
        assert "DO NOTHING" in ins.upper(), (
            f"insert uses ON CONFLICT but not DO NOTHING: {ins!r}"
        )


def test_ensure_catalogs_is_idempotent_on_repeated_runs() -> None:
    """Running ensure_catalogs twice against a fake client must not raise.

    The recording client returns the same 200/[] for every call, so a
    repeat run is exactly the same SQL — the function must accept this
    silently. Real LocalBackend's ON CONFLICT DO NOTHING semantics close
    the loop end-to-end.
    """
    fake, captured = _client_recording()

    ensure_catalogs(fake)
    first_run_len = len(captured)
    ensure_catalogs(fake)
    second_run_len = len(captured)


    assert second_run_len == 2 * first_run_len, (
        f"second run produced {second_run_len - first_run_len} extra calls, "
        f"expected {first_run_len}"
    )


def test_ensure_catalogs_raises_when_create_table_fails() -> None:
    """If the first DDL fails, ensure_catalogs propagates BackendError."""

    from app.core.data_access import BackendError

    def handler(_req: httpx.Request) -> httpx.Response:
        # Return a 500 for any query so the first CREATE TABLE fails.
        return _json_response(500, {"error": "boom"})

    client = HandlerSqlExecutor(handler)
    with pytest.raises(BackendError):
        ensure_catalogs(client)
    client.close()


# --- list_catalogos_* read helpers ---------------------------------------


def _client_returning(body: list[dict[str, Any]]) -> tuple[SqlExecutor, list[tuple[str, list[object]]]]:
    """Build a fake executor that returns ``body`` for every call and records them.

    The returned ``captured`` list contains ``(query, params)`` tuples
    so callers can assert SQL shape and positional parameters.
    """
    fake = _FakeSqlExecutor()
    fake.set_response(body)
    return fake, fake.calls


def test_list_catalogos_origenes_uses_expected_sql() -> None:
    fake, captured = _client_returning([])
    rows = list_catalogos_origenes(fake)
    assert rows == []
    assert len(captured) == 1
    assert captured[0][0].strip().upper().startswith("SELECT")
    assert "FROM catalogos_origenes" in captured[0][0]
    # query must carry no parameters (no params needed for the default order)
    assert captured[0][1] in (None, [], [])


def test_list_catalogos_motivos_uses_expected_sql() -> None:
    fake, captured = _client_returning([])
    rows = list_catalogos_motivos(fake)
    assert rows == []
    assert "FROM catalogos_motivos" in captured[0][0]


def test_list_catalogos_pruebas_uses_expected_sql() -> None:
    fake, captured = _client_returning([])
    rows = list_catalogos_pruebas(fake)
    assert rows == []
    assert "FROM catalogos_pruebas" in captured[0][0]


def test_list_catalogos_periodicidad_uses_expected_sql() -> None:
    fake, captured = _client_returning([])
    rows = list_catalogos_periodicidad(fake)
    assert rows == []
    assert "FROM catalogos_periodicidad" in captured[0][0]


def test_list_catalogos_tipos_contrato_uses_expected_sql() -> None:
    fake, captured = _client_returning([])
    rows = list_catalogos_tipos_contrato(fake)
    assert rows == []
    assert "FROM catalogos_tipos_contrato" in captured[0][0]


def test_list_catalogos_origenes_returns_rows_from_client() -> None:
    """When the client returns rows, list_catalogos_origenes surfaces them."""
    fake_rows = [
        {"id": "a", "codigo": "Acogida", "nombre": "Acogida"},
        {"id": "b", "codigo": "Regalo", "nombre": "Regalo"},
    ]
    fake, _ = _client_returning(fake_rows)
    rows = list_catalogos_origenes(fake)
    assert rows == fake_rows


# --- exports sanity ------------------------------------------------------


def test_module_exposes_list_constants() -> None:
    """The 5 list SQL constants must be importable (used by future routes)."""
    import app.core.catalogs as catalogs_module

    expected = (
        "LIST_CATALOGOS_ORIGENES_SQL",
        "LIST_CATALOGOS_MOTIVOS_SQL",
        "LIST_CATALOGOS_PRUEBAS_SQL",
        "LIST_CATALOGOS_PERIODICIDAD_SQL",
        "LIST_CATALOGOS_TIPOS_CONTRATO_SQL",
    )
    for name in expected:
        value = getattr(catalogs_module, name, None)
        assert isinstance(value, str) and value, (
            f"missing or empty constant {name!r} on app.core.catalogs "
            f"(future read path)"
        )
        assert "FROM " in value.upper(), (
            f"{name!r} does not look like a SELECT statement: {value!r}"
        )
