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
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
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


def test_ensure_domain_schema_creates_all_six_lifecycle_tables() -> None:
    """The bootstrap creates 6 lifecycle tables: 3 originals (animales,
    voluntarios, roles_voluntario) + entradas + acogidas + adopciones
    (LIFECYCLE-03 schema). NOTE: the count is 6 lifecycle tables; the
    full schema also creates 2 lifecycle-event tables
    (animal_lifecycle_events, animal_current_state) added in PR 1 of
    web-only-feature-preservation — see ``test_ensure_domain_schema_creates_eight_tables``
    below for the full count.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

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


# --- entradas (migration-compatible physical schema) ----------------------
#
# Public CRUD scope for the intake entries slice (#87) remains minimal:
# id + animal_id (FK) + optional intake volunteer FK + fecha_entrada +
# origen/motivo/observaciones + soft-delete/timestamps. The physical table
# still keeps nullable salida/entrega/donativo columns because entrada.yaml
# maps legacy data into them until a dedicated migration-mapping change exists.


def test_entradas_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS entradas" in ENTRADAS_CREATE_TABLE_SQL


def test_entradas_create_table_sql_has_minimal_public_crud_columns() -> None:
    """The #87 public CRUD contract is the minimal intake-entry surface."""
    columns = _column_names(ENTRADAS_CREATE_TABLE_SQL)
    required = {
        "id",
        "animal_id",
        "voluntario_entrada_id",
        "fecha_entrada",
        "origen",
        "motivo",
        "observaciones",
        "fecha_alta",
        "updated_at",
        "activo",
    }
    missing = required - columns
    assert not missing, f"entradas table missing columns: {sorted(missing)}"


def test_entradas_create_table_sql_keeps_migration_mapped_physical_columns() -> None:
    """Mapped legacy fields remain physical columns for entrada.yaml compatibility."""
    columns = _column_names(ENTRADAS_CREATE_TABLE_SQL)
    mapped_deferred_columns = {
        "voluntario_salida_id",
        "fecha_salida",
        "fecha_entrega_propietario",
        "donativo_entregador",
    }
    missing = mapped_deferred_columns - columns
    assert not missing, f"entradas table missing mapped columns: {sorted(missing)}"


def test_entradas_migration_mapped_columns_are_nullable_and_deferred() -> None:
    """Migration-only columns must not become mandatory public CRUD fields."""
    sql = ENTRADAS_CREATE_TABLE_SQL
    assert "voluntario_salida_id UUID REFERENCES voluntarios(id)" in sql
    assert "fecha_salida DATE" in sql
    assert "fecha_entrega_propietario DATE" in sql
    assert "donativo_entregador NUMERIC(10,2)" in sql
    for column in (
        "voluntario_salida_id",
        "fecha_salida",
        "fecha_entrega_propietario",
        "donativo_entregador",
    ):
        assert f"{column} " in sql
        assert f"{column} " + "TEXT NOT NULL" not in sql
        assert f"{column} " + "DATE NOT NULL" not in sql
        assert f"{column} " + "UUID NOT NULL" not in sql
        assert f"{column} " + "NUMERIC(10,2) NOT NULL" not in sql


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
    """All 6 lifecycle tables are created, in FK-respecting order:

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
    # Dependency order — the first 6 are the lifecycle tables.
    assert queries[0].startswith("CREATE TABLE IF NOT EXISTS animales")
    assert queries[1].startswith("CREATE TABLE IF NOT EXISTS voluntarios")
    assert queries[2].startswith("CREATE TABLE IF NOT EXISTS roles_voluntario")
    assert queries[3].startswith("CREATE TABLE IF NOT EXISTS entradas")
    assert queries[4].startswith("CREATE TABLE IF NOT EXISTS acogidas")
    assert queries[5].startswith("CREATE TABLE IF NOT EXISTS adopciones")


# --- animal_lifecycle_events (LIFECYCLE-SCHEMA-02) -----------------------
#
# PR 1 of web-only-feature-preservation: the two new tables in
# docs/discovery/lifecycle-event-log-design.md §3.1-3.2 are P0 BLOCKERS
# for PR 2 (derivation engine + semantic events). They MUST be added to
# ensure_domain_schema() before any derivation work can compile.


def test_animal_lifecycle_events_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS animal_lifecycle_events" in (
        ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL
    )


def test_animal_lifecycle_events_has_required_columns() -> None:
    """Schema per docs/discovery/lifecycle-event-log-design.md §3.1.

    Required columns: id, animal_id, event_type, event_timestamp,
    caused_by_event_id (nullable), source_entity_type (nullable),
    source_entity_id (nullable), legacy_source_table (nullable),
    legacy_source_id (nullable), metadata (JSONB), created_by, created_at.
    """
    columns = _column_names(ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL)
    required = {
        "id",
        "animal_id",
        "event_type",
        "event_timestamp",
        "caused_by_event_id",
        "source_entity_type",
        "source_entity_id",
        "legacy_source_table",
        "legacy_source_id",
        "metadata",
        "created_by",
        "created_at",
    }
    missing = required - columns
    assert not missing, f"animal_lifecycle_events missing columns: {sorted(missing)}"


def test_animal_lifecycle_events_event_type_is_varchar_with_check() -> None:
    """event_type is VARCHAR(50) with a CHECK (the constraint name may be inline)."""
    sql = ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL
    assert "event_type" in sql
    assert "CHECK" in sql
    # Concrete values from §4 of the design doc.
    assert "INTAKE_STARTED" in sql
    assert "DEATH_RECORDED" in sql


def test_animal_lifecycle_events_fk_animal_id_to_animales() -> None:
    """animal_id REFERENCES animales(id) is mandatory (every event belongs to an animal)."""
    pairs = _fk_targets(ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL)
    assert ("animal_id", "animales") in pairs


def test_animal_lifecycle_events_event_timestamp_not_null() -> None:
    """event_timestamp NOT NULL — every event must carry a wall-clock moment."""
    assert "event_timestamp TIMESTAMPTZ NOT NULL" in ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL


def test_animal_lifecycle_events_natural_key_unique_constraint() -> None:
    """UNIQUE (animal_id, event_type, event_timestamp) — natural-key
    uniqueness enables INSERT idempotence at the DB level.

    Background (PR 4 follow-up, P1 #2): the lifecycle-event persister
    (``app/core/migration/reconcile.py::_persist_lifecycle_event``)
    uses ``INSERT ... ON CONFLICT (animal_id, event_type,
    event_timestamp) DO NOTHING`` so a retry apply after a post-COMMIT
    failure does NOT create a duplicate event row. The UNIQUE
    constraint is what makes the ``ON CONFLICT`` clause resolve to a
    no-op rather than a constraint violation that aborts the batch.

    Without this constraint, a retry would create a duplicate row that
    the animal state machine would count as a second transition for
    the same logical event — silent data corruption. The constraint
    + DO NOTHING combo is the DB-level idempotence guard.
    """
    sql = ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL
    assert "UNIQUE (animal_id, event_type, event_timestamp)" in sql, (
        "animal_lifecycle_events must declare UNIQUE "
        "(animal_id, event_type, event_timestamp) for the ON CONFLICT "
        "DO NOTHING idempotence guard in the lifecycle-event persister; "
        f"got SQL without it: {sql!r}"
    )


# --- animal_current_state (LIFECYCLE-SCHEMA-02) ---------------------------


def test_animal_current_state_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS animal_current_state" in (
        ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
    )


def test_animal_current_state_has_required_columns() -> None:
    """Schema per docs/discovery/lifecycle-event-log-design.md §3.2.

    Required columns: animal_id (PK + FK), current_state (VARCHAR NOT NULL
    CHECK), active_event_id (nullable), active_intake_id (nullable),
    active_foster_id (nullable), active_adoption_id (nullable),
    pre_death_state (nullable), state_changed_at, legacy_situacion
    (nullable), legacy_ultimo_estado (nullable), reconciliation_status.
    """
    columns = _column_names(ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL)
    required = {
        "animal_id",
        "current_state",
        "active_event_id",
        "active_intake_id",
        "active_foster_id",
        "active_adoption_id",
        "pre_death_state",
        "state_changed_at",
        "legacy_situacion",
        "legacy_ultimo_estado",
        "reconciliation_status",
    }
    missing = required - columns
    assert not missing, f"animal_current_state missing columns: {sorted(missing)}"


def test_animal_current_state_animal_id_is_primary_key() -> None:
    """animal_id is the PK (1:1 with animales) — there is no separate id UUID."""
    assert "animal_id UUID PRIMARY KEY" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL


def test_animal_current_state_reconciliation_status_defaults_to_pending() -> None:
    """reconciliation_status defaults to 'pending' so newly inserted rows do not claim a status."""
    assert "reconciliation_status" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL
    assert "DEFAULT 'pending'" in ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL


# --- ensure_domain_schema now creates 8 tables (the 2 new ones at the end) -


def test_ensure_domain_schema_creates_eight_tables() -> None:
    """After PR 1, ensure_domain_schema creates 8 tables:

    animales -> voluntarios -> roles_voluntario -> entradas -> acogidas ->
    adopciones -> animal_lifecycle_events -> animal_current_state.

    The two new tables MUST come AFTER adopciones because
    animal_lifecycle_events.animal_id REFERENCES animales and
    animal_current_state.animal_id REFERENCES animales (FK-respecting
    order — adopciones itself only depends on animales/voluntarios/
    entradas, so the new tables can sit at the end).
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    assert len(queries) == 8, f"expected 8 tables, got {len(queries)}: {queries}"
    assert queries[6].startswith("CREATE TABLE IF NOT EXISTS animal_lifecycle_events")
    assert queries[7].startswith("CREATE TABLE IF NOT EXISTS animal_current_state")
