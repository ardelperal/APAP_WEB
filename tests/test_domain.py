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
    ACOGIDAS_ADD_CASA_FK_SQL,
    ACOGIDAS_CREATE_TABLE_SQL,
    ACTUACION_SANITARIA_CREATE_TABLE_SQL,
    ADOPCIONES_CREATE_TABLE_SQL,
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
    ANIMALS_CREATE_TABLE_SQL,
    CESIONES_PROPIETARIO_CREATE_TABLE_SQL,
    CONTRATOS_CREATE_TABLE_SQL,
    ENTRADAS_CREATE_TABLE_SQL,
    FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL,
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
    ``REFERENCES`` keyword (e.g. ``UUID NOT NULL REFERENCES foo(id)``,
    ``UUID NOT NULL UNIQUE REFERENCES foo(id)``).
    """
    pairs: list[tuple[str, str]] = []
    for m in re.finditer(
        r"(\w+)\s+UUID(?:\s+NOT\s+NULL)?(?:\s+UNIQUE)?\s+REFERENCES\s+(\w+)\s*\(\s*id\s*\)",
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


# --- acogidas.casa_acogida_id FK (FOSTER-02, #44) -------------------------
#
# The FK from ``acogidas.casa_acogida_id`` to ``casas_acogida(id)`` was
# added in FOSTER-02 via an explicit ALTER TABLE migration (D-EST-05)
# rather than by editing the original CREATE TABLE — keeps the diff
# between FOSTER-01 and FOSTER-02 explicit and lets the original
# CREATE TABLE stay frozen.
#
# The migration is idempotent (``ADD COLUMN IF NOT EXISTS``) and is
# emitted by ``ensure_domain_schema`` AFTER the CREATE TABLE for
# ``acogidas`` (and AFTER ``casas_acogida`` so the referenced table
# exists). The tests below pin the contract.


def test_acogidas_add_casa_fk_sql_alter_table_is_idempotent() -> None:
    """The migration uses ``ADD COLUMN IF NOT EXISTS`` so re-runs are no-ops."""
    sql = ACOGIDAS_ADD_CASA_FK_SQL
    assert "ALTER TABLE acogidas" in sql
    assert "ADD COLUMN IF NOT EXISTS" in sql
    assert "casa_acogida_id UUID REFERENCES casas_acogida(id)" in sql


def test_acogidas_add_casa_fk_sql_does_not_modify_original_create_table() -> None:
    """The CREATE TABLE for ``acogidas`` does NOT include casa_acogida_id.

    Adding the column to the CREATE TABLE would have been the simpler
    path (D-EST-05 chose ALTER TABLE instead). The test pins the
    contract: the original CREATE TABLE remains frozen so any reader
    parsing it (e.g., the schema docs) sees only the legacy fields.
    """
    columns = _column_names(ACOGIDAS_CREATE_TABLE_SQL)
    assert "casa_acogida_id" not in columns


def test_ensure_domain_schema_emits_casa_fk_migration_after_acogidas_create() -> None:
    """``ensure_domain_schema`` runs the ALTER TABLE after creating ``acogidas``.

    The migration order matters: ``casas_acogida`` must exist before
    the ALTER TABLE references it (Postgres would reject the FK
    otherwise). The ALTER TABLE itself must run AFTER the CREATE TABLE
    for ``acogidas`` — same DB-statement ordering constraint.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    # 14 CREATE TABLE statements (12 lifecycle + foster_capacity_overrides +
    # actuacion_sanitaria for HEALTH-01 #50) + 1 ALTER TABLE for the casa FK.
    # FOSTER-03 (#45) added ``foster_capacity_overrides``; ordering still
    # puts it after the ALTER TABLE so the FOSTER slice is contiguous.
    # HEALTH-01 (#50) appended ``actuacion_sanitaria`` at the very end of
    # ``ensure_domain_schema`` so the FKs to ``animales`` /
    # ``catalogos_pruebas`` / ``voluntarios`` are satisfied on subsequent
    # boots (catalog tables exist by then).
    create_queries = [
        q for q in queries if q.startswith("CREATE TABLE IF NOT EXISTS")
    ]
    alter_queries = [q for q in queries if q.startswith("ALTER TABLE")]
    assert len(create_queries) == 14, (
        f"expected 14 CREATE TABLEs, got {len(create_queries)}: {create_queries}"
    )
    assert len(alter_queries) == 1, (
        f"expected 1 ALTER TABLE (FOSTER-02 casa FK), got {len(alter_queries)}: {alter_queries}"
    )
    # The ALTER TABLE must come AFTER the CREATE TABLE for ``acogidas``
    # and AFTER the CREATE TABLE for ``casas_acogida``.
    create_acogidas_idx = next(
        i for i, q in enumerate(create_queries)
        if q.startswith("CREATE TABLE IF NOT EXISTS acogidas")
    )
    create_casas_acogida_idx = next(
        i for i, q in enumerate(create_queries)
        if q.startswith("CREATE TABLE IF NOT EXISTS casas_acogida")
    )
    alter_idx = next(
        i for i, q in enumerate(queries) if q.startswith("ALTER TABLE")
    )
    assert alter_idx > create_acogidas_idx, (
        "ALTER TABLE acogidas ADD COLUMN must run AFTER CREATE TABLE acogidas"
    )
    assert alter_idx > create_casas_acogida_idx, (
        "ALTER TABLE must run AFTER CREATE TABLE casas_acogida (FK target must exist)"
    )


# --- foster_capacity_overrides (FOSTER-03, #45) ---------------------------
#
# Audit log para los overrides de capacidad. 6 columnas: id PK + FKs a
# casas_acogida y animales + operador_user_id (UUID libre, integridad a
# nivel de aplicación) + motivo TEXT NOT NULL + created_at. Se posiciona
# DESPUÉS del ALTER TABLE de ``acogidas`` para mantener el orden
# lógico del slice foster.


def test_foster_capacity_overrides_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS foster_capacity_overrides" in (
        FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL
    )


def test_foster_capacity_overrides_create_table_sql_columns() -> None:
    columns = _column_names(FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL)
    expected = {
        "id",
        "casa_acogida_id",
        "animal_id",
        "operador_user_id",
        "motivo",
        "created_at",
    }
    assert columns == expected, (
        f"foster_capacity_overrides columns mismatch: extra={columns - expected}, "
        f"missing={expected - columns}"
    )


def test_foster_capacity_overrides_create_table_sql_fks() -> None:
    pairs = _fk_targets(FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL)
    assert ("casa_acogida_id", "casas_acogida") in pairs, (
        "foster_capacity_overrides must FK casa_acogida_id -> casas_acogida(id)"
    )
    assert ("animal_id", "animales") in pairs, (
        "foster_capacity_overrides must FK animal_id -> animales(id)"
    )


def test_foster_capacity_overrides_create_table_sql_motivo_not_null() -> None:
    """motivo TEXT NOT NULL: belt-and-braces contra un INSERT crudo vacío.

    La validación de non-empty vive en ``record_override`` (servicio) +
    en el form check; el NOT NULL es el seguro de vida por si un INSERT
    directo intenta meter un motivo vacío.
    """
    sql = FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL
    assert re.search(r"motivo\s+TEXT\s+NOT\s+NULL", sql), (
        f"motivo must be TEXT NOT NULL in foster_capacity_overrides; got: {sql}"
    )


def test_ensure_domain_schema_emits_foster_capacity_overrides_after_casa_fk_alter() -> None:
    """FOSTER-03 (#45): foster_capacity_overrides runs AFTER the FOSTER-02 ALTER.

    Both ``casas_acogida`` and ``animales`` exist before this CREATE
    TABLE (the former is at idx 5, the latter at idx 0), so the FKs
    declared in ``foster_capacity_overrides`` resolve. The table is
    positioned AFTER the FOSTER-02 ALTER TABLE (idx 7) to keep the
    foster slice contiguous in the lifespan bootstrap.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    create_fco_idx = next(
        i for i, q in enumerate(queries)
        if q.startswith("CREATE TABLE IF NOT EXISTS foster_capacity_overrides")
    )
    alter_idx = next(
        i for i, q in enumerate(queries) if q.startswith("ALTER TABLE")
    )
    assert create_fco_idx > alter_idx, (
        "CREATE TABLE foster_capacity_overrides must run AFTER the "
        "ALTER TABLE acogidas to keep the foster slice contiguous"
    )


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
    a clean database. FOSTER-03 (#45) adds ``foster_capacity_overrides``
    right after the ALTER TABLE for ``acogidas`` but is otherwise
    orthogonal to this 6-table ordering assertion.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    # Dependency order — the first 7 are the lifecycle tables; the
    # INTAKE-02 staging table is interleaved right after ``entradas``
    # because it is logically tied to the intake flow, and
    # ``casas_acogida`` (FOSTER-01) sits BEFORE ``acogidas`` so
    # FOSTER-02 can add an FK from ``acogidas.casa_acogida_id`` to
    # ``casas_acogida.id`` via ALTER TABLE without reordering. FOSTER-02
    # then emits an ALTER TABLE right after the CREATE TABLE for
    # ``acogidas`` to install that FK.
    assert queries[0].startswith("CREATE TABLE IF NOT EXISTS animales")
    assert queries[1].startswith("CREATE TABLE IF NOT EXISTS voluntarios")
    assert queries[2].startswith("CREATE TABLE IF NOT EXISTS roles_voluntario")
    assert queries[3].startswith("CREATE TABLE IF NOT EXISTS entradas")
    assert queries[4].startswith("CREATE TABLE IF NOT EXISTS entradas_batch_staging")
    assert queries[5].startswith("CREATE TABLE IF NOT EXISTS casas_acogida")
    assert queries[6].startswith("CREATE TABLE IF NOT EXISTS acogidas")
    # FOSTER-02: ALTER TABLE immediately after the CREATE TABLE for
    # ``acogidas`` to install the FK to ``casas_acogida``. FOSTER-03
    # (#45) emits ``foster_capacity_overrides`` right after that ALTER,
    # keeping the foster slice contiguous. ``adopciones`` follows.
    assert queries[7].startswith("ALTER TABLE acogidas")
    assert queries[8].startswith("CREATE TABLE IF NOT EXISTS foster_capacity_overrides")
    assert queries[9].startswith("CREATE TABLE IF NOT EXISTS adopciones")


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


def test_ensure_domain_schema_creates_twelve_tables_plus_one_alter() -> None:
    """After issues #41, #40, #43, #44, and #45, ensure_domain_schema emits
    13 CREATE TABLE statements + 1 ALTER TABLE migration:

    animales -> voluntarios -> roles_voluntario -> entradas -> entradas_batch_staging
    -> casas_acogida -> acogidas -> [ALTER TABLE acogidas ADD COLUMN casa_acogida_id]
    -> foster_capacity_overrides -> adopciones -> animal_lifecycle_events
    -> animal_current_state -> cesiones_propietario -> contratos.

    Total statements: 14 (13 CREATE TABLE + 1 ALTER TABLE).

    ``entradas_batch_staging`` (#40, INTAKE-02) sits right after
    ``entradas`` because it is logically tied to the intake flow; it has
    no FK to ``entradas`` (the staging rows ARE the source of future
    ``entradas`` rows), so this ordering is purely a documentation
    choice. ``casas_acogida`` (#43, FOSTER-01) is positioned BEFORE
    ``acogidas`` so FOSTER-02 (#44) can add the FK
    ``acogidas.casa_acogida_id REFERENCES casas_acogida(id)`` via ALTER
    TABLE without reordering. The ALTER TABLE itself runs IMMEDIATELY
    AFTER the CREATE TABLE for ``acogidas`` so the FK target exists.
    ``foster_capacity_overrides`` (#45, FOSTER-03) is positioned right
    AFTER the ALTER TABLE — its FKs target ``casas_acogida`` and
    ``animales`` (both already created) so no extra ordering constraint
    applies beyond "after the foster slice".
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    assert len(queries) == 15, (
        f"expected 15 statements (14 CREATE TABLE + 1 ALTER TABLE), "
        f"got {len(queries)}: {queries}"
    )
    create_queries = [q for q in queries if q.startswith("CREATE TABLE")]
    assert len(create_queries) == 14
    assert queries[0].startswith("CREATE TABLE IF NOT EXISTS animales")
    assert queries[1].startswith("CREATE TABLE IF NOT EXISTS voluntarios")
    assert queries[2].startswith("CREATE TABLE IF NOT EXISTS roles_voluntario")
    assert queries[3].startswith("CREATE TABLE IF NOT EXISTS entradas")
    assert queries[4].startswith("CREATE TABLE IF NOT EXISTS entradas_batch_staging")
    assert queries[5].startswith("CREATE TABLE IF NOT EXISTS casas_acogida")
    assert queries[6].startswith("CREATE TABLE IF NOT EXISTS acogidas")
    # FOSTER-02 ALTER TABLE between ``acogidas`` (idx 6) and ``foster_capacity_overrides`` (idx 8).
    assert queries[7].startswith("ALTER TABLE acogidas")
    assert queries[8].startswith("CREATE TABLE IF NOT EXISTS foster_capacity_overrides")
    assert queries[9].startswith("CREATE TABLE IF NOT EXISTS adopciones")
    assert queries[10].startswith("CREATE TABLE IF NOT EXISTS animal_lifecycle_events")
    assert queries[11].startswith("CREATE TABLE IF NOT EXISTS animal_current_state")
    assert queries[12].startswith("CREATE TABLE IF NOT EXISTS cesiones_propietario")
    assert queries[13].startswith("CREATE TABLE IF NOT EXISTS contratos")


# --- cesiones_propietario (TbCesionPorPropietario legacy, issue #41) ---
#
# Migration target of ``TbCesionPorPropietario`` (P1 fidelity invariant
# of docs/proceso.md §0): one row per owner-surrender event, linked 1-a-1
# to ``entradas`` by FK UNIQUE on ``entrada_id``. 11 records in production
# as of 2026-07-03 (verified via Dysflow, projectId=apap, backendPath=
# Registro_APAP_Alcala_datos_18.accdb).
#
# The contract number (``NCONTRATOCESION`` legacy, format "CP" + 4 digits
# like "CP0671") lives here; the ``contratos`` table (Fase 7) is the
# separate contract-metadata surface with FK to one of the lifecycle
# entities, plus FK to ``catalogos_tipos_contrato`` for the type.


def test_cesiones_propietario_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS cesiones_propietario" in (
        CESIONES_PROPIETARIO_CREATE_TABLE_SQL
    )


def test_cesiones_propietario_has_required_columns() -> None:
    """All columns from ``TbCesionPorPropietario`` must be present
    (P1 fidelity). System improvements (id UUID, fecha_alta, updated_at)
    are added on top of the 19 legacy columns.
    """
    columns = _column_names(CESIONES_PROPIETARIO_CREATE_TABLE_SQL)
    required = {
        # System improvements
        "id",
        "fecha_alta",
        "updated_at",
        # Legacy 1:1 — linkage
        "entrada_id",
        "numero_contrato",
        # Legacy 1:1 — veterinary indicators (Sí/No NULL)
        "cartilla_sanitaria",
        "certificado_veterinario",
        "autorizacion_recogida",
        "fecha_vacuna_rabia",
        "numero_colegiado",
        "numero_colaborador",
        # Legacy 1:1 — owner representative identity
        "nombre_representante",
        "dni_representante",
        # Legacy 1:1 — owner representative address
        "calle_representante",
        "numero_calle_representante",
        "piso_representante",
        "letra_representante",
        "localidad_representante",
        "provincia_representante",
        "cp_representante",
        # Legacy 1:1 — owner representative contact
        "telefono_representante",
        "email_representante",
        # Legacy 1:1 — handover timestamp
        "hora_cesion",
    }
    missing = required - columns
    assert not missing, (
        f"cesiones_propietario table missing columns: {sorted(missing)}"
    )


def test_cesiones_propietario_fk_entrada_id_to_entradas() -> None:
    """entrada_id must reference entradas(id) — every cesión is linked to one intake."""
    pairs = _fk_targets(CESIONES_PROPIETARIO_CREATE_TABLE_SQL)
    assert ("entrada_id", "entradas") in pairs


def test_cesiones_propietario_unique_entrada_id_constraint() -> None:
    """UNIQUE on entrada_id enforces 1:1 with entradas (matching the
    legacy relationship ``TbEntradasTbCesionPorPropietario``, which is
    FK-only, no separate ID — see docs/discovery/feature-02-intake-foster-adoption.md
    §"Owner surrender (Cesión por Propietario)").
    """
    sql = CESIONES_PROPIETARIO_CREATE_TABLE_SQL
    assert "entrada_id UUID NOT NULL UNIQUE" in sql, (
        "cesiones_propietario.entrada_id must be NOT NULL UNIQUE; got "
        f"SQL: {sql!r}"
    )


def test_cesiones_propietario_required_fields_are_not_null() -> None:
    """``entrada_id``, ``numero_contrato`` and ``nombre_representante``
    are NOT NULL. The first two are required in the legacy schema;
    ``nombre_representante`` is nullable in the legacy db but is
    required at the product level (no surrender without an owner), so
    the web schema tightens it.
    """
    sql = CESIONES_PROPIETARIO_CREATE_TABLE_SQL
    assert "entrada_id UUID NOT NULL" in sql
    assert "numero_contrato TEXT NOT NULL" in sql
    assert "nombre_representante TEXT NOT NULL" in sql


def test_cesiones_propietario_veterinary_indicators_check_constraint() -> None:
    """cartilla_sanitaria / certificado_veterinario / autorizacion_recogida
    accept the legacy "Sí"/"No" text values (and NULL — operator can
    leave them blank). BOOLEAN would lose the Spanish-spelled
    affirmative ("Sí" with tilde) that the legacy data uses.
    """
    sql = CESIONES_PROPIETARIO_CREATE_TABLE_SQL
    assert "cartilla_sanitaria TEXT" in sql
    assert "certificado_veterinario TEXT" in sql
    assert "autorizacion_recogida TEXT" in sql
    # The legacy values appear inside the CHECK constraint.
    assert "'Sí'" in sql
    assert "'No'" in sql


# --- contratos (modelo polimórfico Fase 7) --------------------------------
#
# Contract metadata for every workflow that generates one (entrada,
# acogida, adopción, cesión por propietario). The legacy
# ``TbContratosAnexos`` table was already a polymorphic target
# (IDEntrada + IDAcogida + IDAdopcion nullable), referenced by any of
# the lifecycle entities via FK. The web model keeps that shape and
# ADDS the FK to ``catalogos_tipos_contrato`` (CATALOG-01) so each row
# carries its type explicitly — the legacy used a separate
# ``TbPlantillas`` table that was queried by human-readable template
# name, not by FK, which made joins brittle.
#
# The CHECK constraint guarantees exactly one of the four entity FKs is
# populated (a contract belongs to one workflow at a time). The
# type_contrato_id column makes the type explicit at write time.


def test_contratos_create_table_sql_uses_if_not_exists() -> None:
    assert "CREATE TABLE IF NOT EXISTS contratos" in CONTRATOS_CREATE_TABLE_SQL


def test_contratos_has_required_columns() -> None:
    """Required columns: id + tipo_contrato_id FK + numero_contrato +
    fecha + 4 nullable entity FKs + 3 system timestamps + activo +
    nombre_archivo (for future PDF blob) + observaciones.
    """
    columns = _column_names(CONTRATOS_CREATE_TABLE_SQL)
    required = {
        "id",
        "tipo_contrato_id",
        "numero_contrato",
        "fecha",
        "entrada_id",
        "acogida_id",
        "adopcion_id",
        "cesion_id",
        "nombre_archivo",
        "observaciones",
        "fecha_alta",
        "updated_at",
        "activo",
    }
    missing = required - columns
    assert not missing, f"contratos table missing columns: {sorted(missing)}"


def test_contratos_fk_to_all_four_lifecycle_entities() -> None:
    """A contrato may be linked to exactly one of: entrada, acogida,
    adopcion, cesion_propietario. All four FK columns must exist; the
    CHECK constraint enforces mutual exclusivity.
    """
    pairs = _fk_targets(CONTRATOS_CREATE_TABLE_SQL)
    assert ("entrada_id", "entradas") in pairs
    assert ("acogida_id", "acogidas") in pairs
    assert ("adopcion_id", "adopciones") in pairs
    assert ("cesion_id", "cesiones_propietario") in pairs


def test_contratos_fk_tipo_contrato_to_catalogo() -> None:
    """tipo_contrato_id must FK to catalogos_tipos_contrato (CATALOG-01
    seed includes "Cesión" for owner surrender, codigo='Cesión').
    """
    sql = CONTRATOS_CREATE_TABLE_SQL
    assert (
        "tipo_contrato_id UUID NOT NULL REFERENCES catalogos_tipos_contrato(id)"
        in sql
    )


def test_contratos_unique_xor_entity_check_constraint() -> None:
    """A contrato must reference exactly ONE of the four entities — never
    zero (orphan contract), never two (ambiguous ownership). Encode as a
    CHECK over the sum of ``CASE WHEN ... IS NOT NULL THEN 1 ELSE 0 END``.
    """
    sql = CONTRATOS_CREATE_TABLE_SQL
    assert "CONSTRAINT contratos_exactly_one_entity" in sql
    # The check counts each populated FK as 1; sum must equal 1.
    assert (
        "entrada_id IS NOT NULL THEN 1 ELSE 0 END" in sql
        or "entrada_id IS NOT NULL" in sql
    )


def test_contratos_required_metadata_not_null() -> None:
    """tipo_contrato_id, numero_contrato and fecha are NOT NULL — every
    contract has a type, an identifier and a date.
    """
    sql = CONTRATOS_CREATE_TABLE_SQL
    assert "tipo_contrato_id UUID NOT NULL" in sql
    assert "numero_contrato TEXT NOT NULL" in sql
    assert "fecha DATE NOT NULL" in sql


# --- actuacion_sanitaria (HEALTH-01 #50) ----------------------------------
#
# Tabla nueva: historial clinico por animal con la regla D-24 validada
# en la capa de service (no en el schema — el schema solo declara las
# columnas y las FKs).


def test_actuacion_sanitaria_create_table_sql_uses_if_not_exists() -> None:
    """Idempotent creation: re-running the lifespan is safe."""
    assert "CREATE TABLE IF NOT EXISTS actuacion_sanitaria" in (
        ACTUACION_SANITARIA_CREATE_TABLE_SQL
    )


def test_actuacion_sanitaria_create_table_sql_columns() -> None:
    """All 13 columns required by the actuacion_sanitaria table (HEALTH-01).

    10 domain columns (id, animal_id, fecha, tipo_actuacion_id, veterinario,
    observaciones, voluntario_id, material_utilizado, fecha_alta,
    updated_at) + activo + the 3 audit columns. The FKs are checked
    separately.
    """
    columns = _column_names(ACTUACION_SANITARIA_CREATE_TABLE_SQL)
    required = {
        "id",
        "animal_id",
        "fecha",
        "tipo_actuacion_id",
        "veterinario",
        "observaciones",
        "voluntario_id",
        "material_utilizado",
        "fecha_alta",
        "updated_at",
        "activo",
    }
    missing = required - columns
    assert not missing, (
        f"actuacion_sanitaria table missing columns: {sorted(missing)}"
    )


def test_actuacion_sanitaria_create_table_sql_required_columns_not_null() -> None:
    """animal_id and fecha are the only NOT NULL columns besides the PK.

    The legacy contract treats these as the only mandatory fields on a
    clinical event — everything else (tipo_actuacion_id, voluntario_id,
    etc.) is operator-optional.
    """
    sql = ACTUACION_SANITARIA_CREATE_TABLE_SQL
    assert "animal_id UUID NOT NULL" in sql
    assert "fecha DATE NOT NULL" in sql


def test_actuacion_sanitaria_create_table_sql_fk_animal_id_to_animales() -> None:
    """animal_id FK to animales (NOT NULL)."""
    pairs = _fk_targets(ACTUACION_SANITARIA_CREATE_TABLE_SQL)
    assert ("animal_id", "animales") in pairs


def test_actuacion_sanitaria_create_table_sql_fk_tipo_actuacion_id_to_catalogos_pruebas() -> None:
    """tipo_actuacion_id FK to catalogos_pruebas (D-HEALTH-01, CATALOG-01 #65)."""
    pairs = _fk_targets(ACTUACION_SANITARIA_CREATE_TABLE_SQL)
    assert ("tipo_actuacion_id", "catalogos_pruebas") in pairs


def test_actuacion_sanitaria_create_table_sql_fk_voluntario_id_to_voluntarios() -> None:
    """voluntario_id FK to voluntarios (per VOL-05)."""
    pairs = _fk_targets(ACTUACION_SANITARIA_CREATE_TABLE_SQL)
    assert ("voluntario_id", "voluntarios") in pairs


def test_ensure_domain_schema_emits_actuacion_sanitaria_after_contratos() -> None:
    """actuacion_sanitaria is the LAST emit in ensure_domain_schema.

    Placement after ``contratos`` is required because the FKs to
    ``animales``, ``voluntarios``, and ``catalogos_pruebas`` must be
    satisfiable. The lifespan creates catalog tables before domain tables,
    so the FK to ``catalogos_pruebas`` is valid even on a fresh backend.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    assert queries[-1].startswith("CREATE TABLE IF NOT EXISTS actuacion_sanitaria"), (
        f"actuacion_sanitaria must be the LAST emit; got: {queries[-1][:80]!r}"
    )
