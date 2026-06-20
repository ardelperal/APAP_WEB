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
    ANIMALS_CREATE_TABLE_SQL,
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
    ensure_domain_schema,
)
from app.core.insforge import InsForgeClient


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


def test_ensure_domain_schema_creates_all_five_tables_and_indexes() -> None:
    """Slice LIFECYCLE-02 agrega 2 tablas (eventos_ciclo_vida_animal,
    estado_actual_animal) + 6 CREATE INDEX. Total esperado: 3 + 2 + 6 = 11 calls.
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    # 3 CREATE TABLE preexistentes + 2 nuevos (LIFECYCLE-02) + 6 CREATE INDEX
    assert len(captured) == 11, (
        f"expected 11 calls (3 tables + 2 new tables + 6 indexes), got {len(captured)}"
    )
    queries = [c["query"].strip() for c in captured]
    # Las 5 tablas que create_domain_schema debe crear
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS animales") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS voluntarios") for q in queries)
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS roles_voluntario") for q in queries)
    assert any(
        q.startswith("CREATE TABLE IF NOT EXISTS eventos_ciclo_vida_animal") for q in queries
    )
    assert any(q.startswith("CREATE TABLE IF NOT EXISTS estado_actual_animal") for q in queries)
    # Los CREATE INDEX de las 2 tablas nuevas
    create_index_queries = [q for q in queries if q.startswith("CREATE INDEX")]
    assert len(create_index_queries) == 6, (
        f"expected 6 CREATE INDEX, got {len(create_index_queries)}"
    )


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
    with pytest.raises(Exception):  # noqa: PT011 — InsForgeError, asserted by side effect
        ensure_domain_schema(client)
    client.close()


# ============================================================================
# LIFECYCLE-02: log de eventos del ciclo de vida + cache materializado del
# estado actual. Schema inventado para la web (no existe en el Access legacy),
# por lo tanto TODAS las columnas son snake_case espanol coherente con el
# resto del schema web (decision #13454: solo las columnas heredadas del
# legacy respetan CamelCase; las nuevas son snake_case espanol).
# ============================================================================

# Catalogo de los 13 `tipo_evento` del log (issue #68, decision de diseno).
# Son strings snake_case en ingles: son invencion del log web (no existen en
# el legacy) y por eso no siguen el convenio espanol.
TIPO_EVENTO_CATALOGO = frozenset({
    "INTAKE_STARTED",
    "INTAKE_COMPLETED",
    "INTAKE_REOPENED",
    "FOSTER_STARTED",
    "FOSTER_CLOSED_BY_ADOPTION",
    "FOSTER_RETURNED",
    "FOSTER_REOPENED",
    "ADOPTION_STARTED",
    "ADOPTION_RETURNED",
    "ADOPTION_REOPENED",
    "OWNER_RETURNED",
    "DEATH_RECORDED",
    "STATE_CORRECTION",
})

# Catalogo DameSituacion (strings EXACTOS, issue #69).
SITUACION_BASE = frozenset({
    "Pendiente de Entrada",
    "Pendiente de Nueva Situacion",  # sin enie por el encoding del motor
    "Albergue",
    "Acogida",
    "Adoptado",
    "Entregado",
    "Incoherente",
})

ESTADO_RECONCILIACION_CATALOGO = frozenset({
    "pending",
    "matched",
    "divergent",
    "migrated",
})


# --- eventos_ciclo_vida_animal (issue #68) -------------------------------


def test_eventos_ciclo_vida_animal_create_table_sql_existe() -> None:
    """La constante Python del SQL existe y crea la tabla esperada."""
    from app.core.domain import EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL

    assert "CREATE TABLE IF NOT EXISTS eventos_ciclo_vida_animal" in (
        EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL
    )


def test_eventos_todas_las_columnas_esperadas() -> None:
    """Las 13 columnas del log de eventos (sin `estado_previo_muerte`, sin
    `creado_en` — ver tests #15 y #16).
    """
    from app.core.domain import EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL

    columns = _column_names(EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL)
    required = {
        "id",
        "animal_id",
        "tipo_evento",
        "fecha_evento",
        "evento_causa_id",
        "tabla_origen_legacy",
        "id_origen_legacy",
        "fuente_entidad_tipo",
        "fuente_entidad_id",
        "metadatos",
        "creado_por",
        "fecha_creacion",
        "activo",
    }
    missing = required - columns
    assert not missing, (
        f"eventos_ciclo_vida_animal missing columns: {sorted(missing)}; "
        f"present columns: {sorted(columns)}"
    )


def test_eventos_fk_animal_id_a_animales() -> None:
    """animal_id FK hacia animales(id), NOT NULL (todo evento requiere animal)."""
    from app.core.domain import EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL

    sql = EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL
    pairs = _fk_targets(sql)
    assert ("animal_id", "animales") in pairs, (
        f"eventos_ciclo_vida_animal debe tener FK animal_id -> animales(id); "
        f"FK pairs encontrados: {pairs}"
    )
    # Verificacion adicional: la columna es NOT NULL (un evento sin animal no
    # tiene sentido). Buscamos la declaracion exacta de la columna.
    assert re.search(
        r"animal_id\s+UUID\s+NOT\s+NULL\s+REFERENCES\s+animales\s*\(\s*id\s*\)",
        sql,
    ), "animal_id debe declararse NOT NULL REFERENCES animales(id)"


def test_eventos_fk_evento_causa_id_self_referencing() -> None:
    """evento_causa_id FK a la propia tabla (cadena causal: ADOPTDEVUELTA).

    Debe ser NULLABLE: solo eventos derivados (synthetic) tienen causa.
    """
    from app.core.domain import EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL

    sql = EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL
    # Buscamos la columna como declaracion de columna (no como table-level FK
    # ya que el diseno propuesto es column-level REFERENCES).
    assert re.search(
        r"evento_causa_id\s+UUID\s+REFERENCES\s+eventos_ciclo_vida_animal\s*\(\s*id\s*\)",
        sql,
    ), (
        "evento_causa_id debe ser UUID REFERENCES eventos_ciclo_vida_animal(id) "
        "NULLABLE (sin NOT NULL)"
    )
    # Y NO debe ser NOT NULL (es opcional).
    assert not re.search(
        r"evento_causa_id\s+UUID\s+NOT\s+NULL",
        sql,
    ), "evento_causa_id debe ser NULLABLE (no NOT NULL)"


def test_eventos_fk_creado_por_a_usuarios_autorizados() -> None:
    """creado_por FK a la tabla web de autenticacion (NO 'usuarios' generico).

    La tabla de autenticacion del web se llama `usuarios_autorizados`
    (creada en `app/core/auth.py`). Si la FK apuntara a una tabla inexistente,
    el INSERT fallaria en runtime.
    """
    from app.core.domain import EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL

    sql = EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL
    pairs = _fk_targets(sql)
    assert ("creado_por", "usuarios_autorizados") in pairs, (
        f"eventos_ciclo_vida_animal.creado_por debe apuntar a "
        f"usuarios_autorizados(id); FK pairs encontrados: {pairs}"
    )
    # Guard contra regresion: NO debe apuntar a una tabla 'usuarios' generica
    # (esa tabla no existe en el schema actual).
    assert ("creado_por", "usuarios") not in pairs, (
        "creado_por NO debe apuntar a tabla 'usuarios' generica; debe apuntar "
        "a 'usuarios_autorizados' (ver app/core/auth.py)"
    )


def test_eventos_check_tipo_evento_cubre_los_13_valores() -> None:
    """El CHECK constraint de tipo_evento incluye los 13 strings del catalogo."""
    from app.core.domain import EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL

    sql = EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL
    # Extraemos el contenido del CHECK de tipo_evento
    match = re.search(
        r"tipo_evento\s+VARCHAR\(\d+\)\s+NOT\s+NULL\s+CHECK\s*\(\s*tipo_evento\s+IN\s*\(([^)]+)\)",
        sql,
    )
    assert match is not None, (
        "no se encontro CHECK constraint para tipo_evento; "
        f"SQL: {sql!r}"
    )
    contenido = match.group(1)
    # Cada valor del catalogo debe aparecer literal (con comillas simples) en el CHECK
    for valor in TIPO_EVENTO_CATALOGO:
        assert f"'{valor}'" in contenido, (
            f"CHECK de tipo_evento no incluye '{valor}'; contenido: {contenido!r}"
        )


def test_eventos_tiene_columnas_soft_delete_activo() -> None:
    """La columna activo BOOLEAN DEFAULT true existe en AMBAS tablas
    (eventos_ciclo_vida_animal y estado_actual_animal) para soft-delete."""
    from app.core.domain import (
        ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL,
        EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL,
    )

    pattern = r"activo\s+BOOLEAN\s+NOT\s+NULL\s+DEFAULT\s+true"
    assert re.search(pattern, EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL), (
        "eventos_ciclo_vida_animal debe tener `activo BOOLEAN NOT NULL DEFAULT true`"
    )
    assert re.search(pattern, ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL), (
        "estado_actual_animal debe tener `activo BOOLEAN NOT NULL DEFAULT true`"
    )


def test_NO_existe_creado_en_en_eventos() -> None:
    """Guard explicito contra el nombre ingles `creado_en`/`created_at`.

    El resto del schema web usa `fecha_alta`/`fecha_creacion` en espanol
    (decision de naming del proyecto). `creado_en` rompe la consistencia.
    """
    from app.core.domain import EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL

    columns = _column_names(EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL)
    assert "creado_en" not in columns, (
        "eventos_ciclo_vida_animal NO debe usar 'creado_en' (ingles); "
        "usar 'fecha_creacion' (espanol, consistente con fecha_alta/updated_at)"
    )
    assert "created_at" not in columns, (
        "eventos_ciclo_vida_animal NO debe usar 'created_at' (ingles); "
        "usar 'fecha_creacion' (espanol)"
    )
    assert "fecha_creacion" in columns, (
        "eventos_ciclo_vida_animal debe tener 'fecha_creacion' (no 'creado_en')"
    )


# --- estado_actual_animal (issue #69) -----------------------------------


def test_estado_actual_animal_create_table_sql_existe() -> None:
    """La constante Python del SQL existe y crea la tabla esperada."""
    from app.core.domain import ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL

    assert "CREATE TABLE IF NOT EXISTS estado_actual_animal" in (
        ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL
    )


def test_estado_actual_todas_las_columnas_esperadas() -> None:
    """Las 10 columnas del cache de estado (SIN `estado_previo_muerte`).

    `estado_previo_muerte` se omite a proposito porque el dato ya existe
    en `animales.UltimoEstadoAntesDeFallecido` (CamelCase legacy, ya migrado).
    Si una query lo necesita, hace JOIN. Duplicar seria redundancia.
    """
    from app.core.domain import ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL

    columns = _column_names(ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL)
    required = {
        "animal_id",
        "situacion_actual",
        "evento_activo_id",
        "intake_activo_id",
        "foster_activo_id",
        "adopcion_activa_id",
        "fecha_cambio_estado",
        "situacion_legacy",
        "estado_reconciliacion",
        "activo",
    }
    missing = required - columns
    assert not missing, (
        f"estado_actual_animal missing columns: {sorted(missing)}; "
        f"present columns: {sorted(columns)}"
    )


def test_estado_actual_fk_animal_id_a_animales() -> None:
    """animal_id es la PRIMARY KEY (1:1 con animales) y FK a animales(id)."""
    from app.core.domain import ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL

    sql = ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL
    # Debe existir la declaracion PK + FK en la misma columna
    assert re.search(
        r"animal_id\s+UUID\s+PRIMARY\s+KEY\s+REFERENCES\s+animales\s*\(\s*id\s*\)",
        sql,
    ), "animal_id debe ser PRIMARY KEY REFERENCES animales(id)"


def test_estado_actual_fk_evento_activo_id_a_eventos() -> None:
    """evento_activo_id FK a eventos_ciclo_vida_animal(id), NULLABLE.

    Es NULLABLE porque un animal puede no tener evento activo (estado
    inicial pre-migracion). El cache se reconstruye a partir de eventos.
    """
    from app.core.domain import ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL

    sql = ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL
    assert re.search(
        r"evento_activo_id\s+UUID\s+REFERENCES\s+eventos_ciclo_vida_animal\s*\(\s*id\s*\)",
        sql,
    ), (
        "evento_activo_id debe ser UUID REFERENCES eventos_ciclo_vida_animal(id) "
        "NULLABLE"
    )
    assert not re.search(
        r"evento_activo_id\s+UUID\s+NOT\s+NULL",
        sql,
    ), "evento_activo_id debe ser NULLABLE (no NOT NULL)"


def _extract_check_content(sql: str, column_name: str) -> str:
    """Extrae el contenido entre ``CHECK (`` y el ``)`` balanceado
    correspondiente para una columna.

    Un regex non-greedy corta en el primer ``)`` (incluyendo el ``)``
    interno de ``VARCHAR(50)`` o los ``(%)`` del LIKE). Esta funcion cuenta
    paréntesis balanceados manualmente.
    """
    pattern = rf"{column_name}\s+VARCHAR\(\d+\)\s+NOT\s+NULL\s+CHECK\s*\("
    match = re.search(pattern, sql)
    assert match is not None, (
        f"no se encontro CHECK constraint para {column_name}; SQL: {sql!r}"
    )
    start = match.end()
    depth = 1
    i = start
    while i < len(sql) and depth > 0:
        char = sql[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        i += 1
    assert depth == 0, f"paréntesis no balanceados en CHECK de {column_name}"
    return sql[start : i - 1]


def test_estado_actual_check_situacion_cubre_los_7_valores_mas_like_fallecido() -> None:
    """El CHECK de situacion_actual incluye los 7 strings DameSituacion + LIKE 'Fallecido (%)'."""
    from app.core.domain import ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL

    sql = ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL
    contenido = _extract_check_content(sql, "situacion_actual")
    # Los 7 valores base deben aparecer literalmente (con comillas simples)
    for valor in SITUACION_BASE:
        assert f"'{valor}'" in contenido, (
            f"CHECK de situacion_actual no incluye '{valor}'; contenido: {contenido!r}"
        )
    # Fallecido se acepta por patron LIKE 'Fallecido (%)'
    assert "LIKE 'Fallecido (%)'" in contenido, (
        f"CHECK de situacion_actual debe aceptar LIKE 'Fallecido (%)' "
        f"para cubrir Fallecido (Albergue/Acogida/Adoptado/Entregado/Desconocido); "
        f"contenido: {contenido!r}"
    )


def test_estado_actual_check_estado_reconciliacion_cubre_los_4_valores() -> None:
    """El CHECK de estado_reconciliacion cubre pending/matched/divergent/migrated."""
    from app.core.domain import ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL

    sql = ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL
    match = re.search(
        r"estado_reconciliacion\s+VARCHAR\(\d+\)\s+NOT\s+NULL\s+DEFAULT\s+'pending'\s+CHECK\s*\(\s*estado_reconciliacion\s+IN\s*\(([^)]+)\)",
        sql,
    )
    assert match is not None, (
        "no se encontro CHECK constraint para estado_reconciliacion con DEFAULT 'pending'; "
        f"SQL: {sql!r}"
    )
    contenido = match.group(1)
    for valor in ESTADO_RECONCILIACION_CATALOGO:
        assert f"'{valor}'" in contenido, (
            f"CHECK de estado_reconciliacion no incluye '{valor}'; contenido: {contenido!r}"
        )


def test_NO_existe_estado_previo_muerte_en_estado_actual_animal() -> None:
    """Guard explicito contra la columna redundante `estado_previo_muerte`.

    El dato ya existe en `animales.UltimoEstadoAntesDeFallecido` (CamelCase
    legacy, ya migrado a la tabla animales). Duplicar el dato en
    `estado_actual_animal` es redundancia y abre la puerta a drift entre
    las dos copias. La decision es JOIN a animales cuando se necesite.
    """
    from app.core.domain import ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL

    columns = _column_names(ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL)
    assert "estado_previo_muerte" not in columns, (
        "estado_actual_animal NO debe tener columna 'estado_previo_muerte'; "
        "el dato ya esta en animales.UltimoEstadoAntesDeFallecido (legacy). "
        "Hacer JOIN a animales cuando se necesite."
    )
    # Guard contra la variante que alguien podria proponer (snake_case ingles)
    assert "estado_pre_muerte" not in columns, (
        "estado_actual_animal NO debe tener 'estado_pre_muerte' (variante inglesa)"
    )


# --- orden de ensure_domain_schema (5 tablas en orden correcto) ----------


def test_ensure_domain_schema_crea_las_5_tablas_en_orden() -> None:
    """Orden estricto: animales -> voluntarios -> roles_voluntario ->
    eventos_ciclo_vida_animal -> estado_actual_animal.

    Cualquier otro orden falla por FKs:
    - roles_voluntario referencia voluntarios (debe existir antes).
    - eventos_ciclo_vida_animal referencia animales (debe existir antes).
    - estado_actual_animal referencia animales + eventos (deben existir antes).
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    client.close()

    queries = [c["query"].strip() for c in captured]
    # Las 5 CREATE TABLE deben aparecer en este orden estricto entre si
    create_table_queries = [
        q for q in queries if q.startswith("CREATE TABLE IF NOT EXISTS")
    ]
    assert len(create_table_queries) == 5, (
        f"expected 5 CREATE TABLE, got {len(create_table_queries)}: {create_table_queries!r}"
    )
    assert create_table_queries[0].startswith(
        "CREATE TABLE IF NOT EXISTS animales"
    ), f"queries[0] debe ser animales; got {create_table_queries[0]!r}"
    assert create_table_queries[1].startswith(
        "CREATE TABLE IF NOT EXISTS voluntarios"
    ), f"queries[1] debe ser voluntarios; got {create_table_queries[1]!r}"
    assert create_table_queries[2].startswith(
        "CREATE TABLE IF NOT EXISTS roles_voluntario"
    ), f"queries[2] debe ser roles_voluntario; got {create_table_queries[2]!r}"
    assert create_table_queries[3].startswith(
        "CREATE TABLE IF NOT EXISTS eventos_ciclo_vida_animal"
    ), f"queries[3] debe ser eventos_ciclo_vida_animal; got {create_table_queries[3]!r}"
    assert create_table_queries[4].startswith(
        "CREATE TABLE IF NOT EXISTS estado_actual_animal"
    ), f"queries[4] debe ser estado_actual_animal; got {create_table_queries[4]!r}"


def test_ensure_domain_schema_no_duplica_tablas_existentes() -> None:
    """Idempotencia: ejecutar 2 veces no rompe (CREATE TABLE IF NOT EXISTS +
    CREATE INDEX IF NOT EXISTS son idempotentes por si mismos; la prueba
    documenta el contrato).
    """
    client, captured = _client_recording(lambda req, body: _json_response(200, []))

    ensure_domain_schema(client)
    ensure_domain_schema(client)  # segunda vez
    client.close()

    # Cada ejecucion produce 11 calls; 2 ejecuciones = 22 calls totales
    assert len(captured) == 22, (
        f"expected 22 calls (11 + 11), got {len(captured)}"
    )
    # Ninguna query tiene ALTER/DROP (no estamos recreando tablas)
    for call in captured:
        query = call["query"].strip()
        assert not query.startswith("DROP"), (
            f"ensure_domain_schema no debe ejecutar DROP; found: {query!r}"
        )
        assert not query.startswith("ALTER"), (
            f"ensure_domain_schema no debe ejecutar ALTER; found: {query!r}"
        )
