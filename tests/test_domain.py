"""Tests for the domain schema bootstrap (animales, voluntarios, roles_voluntario).

Mirrors the pattern in ``tests/test_auth.py``: real ``InsForgeClient`` with
``httpx.MockTransport`` so we exercise the SQL strings, params, and
response parsing without hitting the network. The schema definitions
are verified structurally (columns, types, constraints, FKs) by parsing
the SQL strings, which keeps the test honest about what the code intends
to create.

The schema is the **migration target** of the legacy Microsoft Access
production database (issue #29). Field names use the exact legacy
CamelCase Spanish spelling (NCHIP, NombreAnimal, FIMPLANTACIONCHIP,
FNacimiento, FDefuncion, etc.) to keep the migration a near-1:1 column
copy. The ``Situacion`` legacy column is intentionally absent because
it is derived.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from app.core.domain import (
    ACOGIDAS_CREATE_TABLE_SQL,
    ADOPCIONES_CREATE_TABLE_SQL,
    ANIMALS_CREATE_TABLE_SQL,
    ENTRADAS_CREATE_TABLE_SQL,
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
    ensure_domain_schema,
)
from app.core.insforge import InsForgeClient, InsForgeError


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(handler) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    """Build a client whose MockTransport records every call's JSON body."""
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


def _column_names(sql: str) -> set[str]:
    """Return the set of column names declared in a CREATE TABLE statement.

    Naive parser: finds the parenthesised body of ``CREATE TABLE [IF NOT
    EXISTS] <name> ( ... )`` and splits on commas at depth 0. Good enough
    for the column names we want to assert; foreign-key targets live in a
    separate ``REFERENCES`` clause and are tested directly.
    """
    match = re.search(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+\w+\s*\((.*)\)\s*$", sql, re.DOTALL)
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
        # Skip constraint lines (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK)
        if first.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            continue
        names.add(first)
    return names


def _fk_targets(sql: str) -> list[tuple[str, str]]:
    """Return the list of (column, referenced_table) pairs declared via REFERENCES.

    Tolerates column-level constraints between the type and the
    ``REFERENCES`` keyword (e.g. ``UUID NOT NULL REFERENCES foo(id)``).
    """
    pairs: list[tuple[str, str]] = []
    for m in re.finditer(
        r"(\w+)\s+UUID(?:\s+NOT\s+NULL)?\s+REFERENCES\s+(\w+)\s*\(\s*id\s*\)",
        sql,
    ):
        pairs.append((m.group(1), m.group(2)))
    return pairs


# --- animales -------------------------------------------------------------


def test_animales_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS animales" in ANIMALS_CREATE_TABLE_SQL


def test_animales_create_table_sql_has_all_legacy_columns() -> None:
    """Every column from TbFichaAnimal (issue #29) must be present.

    Reference: Dysflow inspection of
    C:\\00repos\\codigo\\APAP_ACTUAL\\Registro_APAP_Alcala_datos_18.accdb
    on 2026-06-19. The 26 legacy columns are:
    NCHIP, TraeNChip, FIMPLANTACIONCHIP, NombreAnimal, Especie, Sexo,
    Raza, Color, Pelo, Tamanyos (legacy encoding), Caracter, FNacimiento,
    FDefuncion, Terapia, Observaciones, Situacion (REMOVED — derived),
    NombreFoto, Cartilla, Eutanasia, RazaPPP, Mestizo,
    EutanasiaOtrasCausas, EutanasiaEnfermedad, UltimoEstadoAntesDeFallecido,
    ComunicacionARIAC.
    Plus 3 justified improvements: id, fecha_alta, updated_at, activo.
    """
    columns = _column_names(ANIMALS_CREATE_TABLE_SQL)
    required = {
        # System columns (improvements)
        "id",
        "fecha_alta",
        "updated_at",
        "activo",
        # Identity (legacy 1:1)
        "NCHIP",
        "TraeNChip",
        "FIMPLANTACIONCHIP",
        "NombreAnimal",
        # Domain (legacy 1:1, with CHECK constraints)
        "Especie",
        "Sexo",
        # Physical characteristics (legacy 1:1)
        "Raza",
        "Color",
        "Pelo",
        "Tamano",
        "Caracter",
        # Dates (legacy 1:1)
        "FNacimiento",
        "FDefuncion",
        # Health flags (legacy 1:1)
        "Terapia",
        "Eutanasia",
        "RazaPPP",
        "Mestizo",
        "EutanasiaOtrasCausas",
        "EutanasiaEnfermedad",
        "ComunicacionARIAC",
        # Documentation (legacy 1:1)
        "Observaciones",
        "NombreFoto",
        "Cartilla",
        "UltimoEstadoAntesDeFallecido",
    }
    missing = required - columns
    assert not missing, f"animales table missing legacy columns: {sorted(missing)}"


def test_animales_table_does_not_store_situacion() -> None:
    """Situacion is derived from the event log; it is intentionally not stored."""
    columns = _column_names(ANIMALS_CREATE_TABLE_SQL)
    assert "Situacion" not in columns, (
        "Situacion must be derived from the event log, not stored on animales"
    )


def test_animales_table_enforces_especie_and_sexo_domains() -> None:
    sql = ANIMALS_CREATE_TABLE_SQL
    assert "Especie IN ('CANINA', 'FELINA')" in sql
    assert "Sexo IN ('M', 'H')" in sql


def test_animales_NCHIP_is_unique() -> None:
    assert "NCHIP TEXT UNIQUE NOT NULL" in ANIMALS_CREATE_TABLE_SQL


# --- voluntarios ----------------------------------------------------------


def test_voluntarios_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS voluntarios" in VOLUNTARIOS_CREATE_TABLE_SQL


def test_voluntarios_create_table_sql_has_all_legacy_columns() -> None:
    """Every column from TbVoluntariosParaAutorrellenables must be present.

    Legacy 4 columns: Voluntario, Tel1, Tel2, Email.
    Plus 3 justified improvements: id, DNI, fecha_alta, updated_at, activo.
    """
    columns = _column_names(VOLUNTARIOS_CREATE_TABLE_SQL)
    required = {
        "id",
        "Voluntario",
        "Tel1",
        "Tel2",
        "Email",
        "DNI",
        "fecha_alta",
        "updated_at",
        "activo",
    }
    missing = required - columns
    assert not missing, f"voluntarios table missing columns: {sorted(missing)}"


def test_voluntarios_email_and_DNI_are_unique() -> None:
    assert "Email TEXT UNIQUE" in VOLUNTARIOS_CREATE_TABLE_SQL
    assert "DNI TEXT UNIQUE" in VOLUNTARIOS_CREATE_TABLE_SQL


# --- roles_voluntario -----------------------------------------------------


def test_roles_voluntario_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS roles_voluntario" in ROLES_VOLUNTARIO_CREATE_TABLE_SQL


def test_roles_voluntario_references_voluntarios() -> None:
    pairs = _fk_targets(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
    assert ("voluntario_id", "voluntarios") in pairs


def test_roles_voluntario_enforces_tipo_rol_domain() -> None:
    sql = ROLES_VOLUNTARIO_CREATE_TABLE_SQL
    assert "tipo_rol IN ('intake', 'seguimiento', 'acogida', 'salud')" in sql


def test_roles_voluntario_has_unique_voluntario_rol_pair() -> None:
    assert "UNIQUE (voluntario_id, tipo_rol)" in ROLES_VOLUNTARIO_CREATE_TABLE_SQL


# --- ensure_domain_schema orchestration -----------------------------------


def test_ensure_domain_schema_creates_all_six_tables() -> None:
    """The bootstrap now creates 6 tables: 3 originals + entradas +
    acogidas + adopciones (LIFECYCLE-03 schema).
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    assert len(captured) == 6
    queries = [c["query"].strip() for c in captured]
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS animales") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS voluntarios") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS roles_voluntario") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS entradas") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS acogidas") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS adopciones") for q in queries)


def test_ensure_domain_schema_order_is_animales_then_voluntarios_then_roles() -> None:
    """Roles references voluntarios, voluntarios is independent, animales is independent.

    Order: animales, voluntarios, roles_voluntario. Anything else means a
    foreign-key will fail on a clean database.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    assert queries[0].startswith("CREATE TABLE IF NOT EXISTS animales")
    assert queries[1].startswith("CREATE TABLE IF NOT EXISTS voluntarios")
    assert queries[2].startswith("CREATE TABLE IF NOT EXISTS roles_voluntario")


def test_ensure_domain_schema_raises_when_create_table_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(500, {"error": "boom"})

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(InsForgeError):
        ensure_domain_schema(client)
    client.close()


# --- entradas (TbEntradas legacy) -----------------------------------------
#
# Migration target of TbEntradas from the legacy Access production DB.
# 14 columns: id + animal_id (FK) + 2 voluntario FKs + 3 dates + origen +
# motivo + donativo_entregador + observaciones + 3 system columns.
# Natural-key UNIQUE on (animal_id, fecha_entrada) prevents duplicate
# intakes for the same animal on the same day.


def test_entradas_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS entradas" in ENTRADAS_CREATE_TABLE_SQL


def test_entradas_create_table_sql_columns() -> None:
    """All 14 columns required by the entradas table (LIFECYCLE-03)."""
    columns = _column_names(ENTRADAS_CREATE_TABLE_SQL)
    required = {
        "id",
        "animal_id",
        "voluntario_entrada_id",
        "voluntario_salida_id",
        "fecha_entrada",
        "fecha_salida",
        "fecha_entrega_propietario",
        "origen",
        "motivo",
        "donativo_entregador",
        "observaciones",
        "fecha_alta",
        "updated_at",
        "activo",
    }
    missing = required - columns
    assert not missing, f"entradas table missing columns: {sorted(missing)}"


def test_entradas_create_table_sql_fk_animal_id_to_animales() -> None:
    pairs = _fk_targets(ENTRADAS_CREATE_TABLE_SQL)
    assert ("animal_id", "animales") in pairs


def test_entradas_create_table_sql_fk_voluntario_entrada_id_to_voluntarios() -> None:
    pairs = _fk_targets(ENTRADAS_CREATE_TABLE_SQL)
    assert ("voluntario_entrada_id", "voluntarios") in pairs


def test_entradas_create_table_sql_fk_voluntario_salida_id_to_voluntarios() -> None:
    pairs = _fk_targets(ENTRADAS_CREATE_TABLE_SQL)
    assert ("voluntario_salida_id", "voluntarios") in pairs


def test_entradas_create_table_sql_unique_natural_key_constraint() -> None:
    """Natural key on (animal_id, fecha_entrada) prevents duplicate intakes."""
    assert "CONSTRAINT entradas_natural_key UNIQUE (animal_id, fecha_entrada)" in (
        ENTRADAS_CREATE_TABLE_SQL
    )


# --- acogidas (TbAcogidaAnimal legacy) ------------------------------------
#
# Migration target of TbAcogidaAnimal. 15 columns: id + animal_id FK +
# 4 voluntario FKs (acogida, seguimiento1, seguimiento2, sanitario) +
# fecha_inicio + fecha_final + entrada_origen_id FK + direccion + telefono
# + observaciones + 3 system columns. Natural-key UNIQUE on
# (animal_id, fecha_inicio).


def test_acogidas_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS acogidas" in ACOGIDAS_CREATE_TABLE_SQL


def test_acogidas_create_table_sql_columns() -> None:
    """All 15 columns required by the acogidas table (LIFECYCLE-03)."""
    columns = _column_names(ACOGIDAS_CREATE_TABLE_SQL)
    required = {
        "id",
        "animal_id",
        "voluntario_acogida_id",
        "voluntario_seguimiento1_id",
        "voluntario_seguimiento2_id",
        "voluntario_sanitario_id",
        "fecha_inicio",
        "fecha_final",
        "entrada_origen_id",
        "direccion",
        "telefono",
        "observaciones",
        "fecha_alta",
        "updated_at",
        "activo",
    }
    missing = required - columns
    assert not missing, f"acogidas table missing columns: {sorted(missing)}"


def test_acogidas_create_table_sql_fk_animal_id_to_animales() -> None:
    pairs = _fk_targets(ACOGIDAS_CREATE_TABLE_SQL)
    assert ("animal_id", "animales") in pairs


def test_acogidas_create_table_sql_fk_voluntario_acogida_id_to_voluntarios() -> None:
    pairs = _fk_targets(ACOGIDAS_CREATE_TABLE_SQL)
    assert ("voluntario_acogida_id", "voluntarios") in pairs


def test_acogidas_create_table_sql_fk_entrada_origen_id_to_entradas() -> None:
    pairs = _fk_targets(ACOGIDAS_CREATE_TABLE_SQL)
    assert ("entrada_origen_id", "entradas") in pairs


# --- adopciones (TbAdopcion legacy) ---------------------------------------
#
# Migration target of TbAdopcion. 16 columns: id + animal_id FK +
# voluntario_seguimiento_id FK + 2 dates + 2 donativos + 4 adoptante
# fields (nombre NOT NULL, dni/telefono/email) + entrada_origen_id FK +
# observaciones + 3 system columns. Natural-key UNIQUE on
# (animal_id, fecha_adopcion).


def test_adopciones_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS adopciones" in ADOPCIONES_CREATE_TABLE_SQL


def test_adopciones_create_table_sql_columns() -> None:
    """All 16 columns required by the adopciones table (LIFECYCLE-03)."""
    columns = _column_names(ADOPCIONES_CREATE_TABLE_SQL)
    required = {
        "id",
        "animal_id",
        "voluntario_seguimiento_id",
        "fecha_adopcion",
        "fecha_devolucion",
        "donativo_preadopcion",
        "donativo_adopcion",
        "nombre_adoptante",
        "dni_adoptante",
        "telefono_adoptante",
        "email_adoptante",
        "entrada_origen_id",
        "observaciones",
        "fecha_alta",
        "updated_at",
        "activo",
    }
    missing = required - columns
    assert not missing, f"adopciones table missing columns: {sorted(missing)}"


def test_adopciones_create_table_sql_fk_animal_id_to_animales() -> None:
    pairs = _fk_targets(ADOPCIONES_CREATE_TABLE_SQL)
    assert ("animal_id", "animales") in pairs


def test_adopciones_create_table_sql_fk_voluntario_seguimiento_id_to_voluntarios() -> None:
    pairs = _fk_targets(ADOPCIONES_CREATE_TABLE_SQL)
    assert ("voluntario_seguimiento_id", "voluntarios") in pairs


def test_adopciones_create_table_sql_fk_entrada_origen_id_to_entradas() -> None:
    pairs = _fk_targets(ADOPCIONES_CREATE_TABLE_SQL)
    assert ("entrada_origen_id", "entradas") in pairs


def test_adopciones_create_table_sql_nombre_adoptante_not_null() -> None:
    """nombre_adoptante is the only mandatory adoptante field (legacy contract)."""
    assert "nombre_adoptante TEXT NOT NULL" in ADOPCIONES_CREATE_TABLE_SQL


# --- ensure_domain_schema orchestration with the 3 new tables ----------


def test_ensure_domain_schema_includes_entradas_acogidas_adopciones() -> None:
    """All 6 tables are created, in FK-respecting order:

    animales -> voluntarios -> roles_voluntario -> entradas -> acogidas -> adopciones

    entries depend on animales+voluntarios; acogidas depend on
    animales+voluntarios+entradas; adopciones depend on
    animales+voluntarios+entradas. Any other order means FK will fail on
    a clean database.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    # 6 tables
    assert len(queries) == 6
    # Dependency order
    assert queries[0].startswith("CREATE TABLE IF NOT EXISTS animales")
    assert queries[1].startswith("CREATE TABLE IF NOT EXISTS voluntarios")
    assert queries[2].startswith("CREATE TABLE IF NOT EXISTS roles_voluntario")
    assert queries[3].startswith("CREATE TABLE IF NOT EXISTS entradas")
    assert queries[4].startswith("CREATE TABLE IF NOT EXISTS acogidas")
    assert queries[5].startswith("CREATE TABLE IF NOT EXISTS adopciones")
