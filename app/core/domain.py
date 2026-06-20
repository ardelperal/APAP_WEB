"""Domain schema bootstrap: animales, voluntarios, roles_voluntario,
eventos_ciclo_vida_animal, estado_actual_animal.

Source of truth for the SQL that creates the domain tables in the
InsForge backend. Mirrors the pattern in ``app.core.auth`` for
``authorized_users``: the SQL lives as a constant in Python so the
``CREATE TABLE`` definitions are versioned with the app, and the
``ensure_domain_schema`` function is the single entry point that
``app.main`` calls on startup.

The schema is the **migration target** of the legacy Microsoft Access
production database (``Registro_APAP_Alcala_datos_18.accdb``). HARD
RULES (issue #29):

- ZERO field loss: every column in the legacy schema has a 1:1
  destination here. Field names use the **exact** legacy CamelCase
  Spanish spelling (NCHIP, NombreAnimal, FIMPLANTACIONCHIP, FNacimiento,
  FDefuncion, etc.).
- Improvements are allowed when justified (id UUID PK for stable
  references, fecha_alta for created_at, activo for soft-delete, dni for
  volunteer dedup). New columns are documented as such in the test
  contract.
- The ``Situacion`` legacy column is INTENTIONALLY removed because it
  is derived from the event log, not stored.
- Columnas heredadas del legacy respetan CamelCase exacto. Las
  columnas/mejoras nuevas del web son snake_case espanol coherente
  (decision #13454). Las 2 tablas de este modulo (eventos_ciclo_vida_animal,
  estado_actual_animal) son invenciones del log web: todas sus columnas
  son snake_case espanol consistente.
"""

from __future__ import annotations

from app.core.insforge import InsForgeClient

# --- animales: 1:1 con TbFichaAnimal (26 cols) + 3 mejoras justificadas ---

ANIMALS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    NCHIP TEXT UNIQUE NOT NULL,
    TraeNChip TEXT,
    FIMPLANTACIONCHIP DATE,
    NombreAnimal TEXT NOT NULL,
    Especie TEXT NOT NULL CHECK (Especie IN ('CANINA', 'FELINA')),
    Sexo TEXT NOT NULL CHECK (Sexo IN ('M', 'H')),
    Raza TEXT,
    Color TEXT,
    Pelo TEXT,
    Tamano TEXT,
    Caracter TEXT,
    FNacimiento DATE NOT NULL,
    FDefuncion DATE,
    Terapia TEXT,
    Observaciones TEXT,
    NombreFoto TEXT,
    Cartilla TEXT,
    Eutanasia TEXT,
    RazaPPP TEXT,
    Mestizo TEXT,
    EutanasiaOtrasCausas TEXT,
    EutanasiaEnfermedad TEXT,
    UltimoEstadoAntesDeFallecido TEXT,
    ComunicacionARIAC TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

# --- voluntarios: TbVoluntariosParaAutorrellenables (4 cols) + 3 mejoras ---

VOLUNTARIOS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS voluntarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    Voluntario TEXT NOT NULL,
    Tel1 TEXT,
    Tel2 TEXT,
    Email TEXT UNIQUE,
    DNI TEXT UNIQUE,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

# --- roles_voluntario (renombre de volunteer_roles) ---

ROLES_VOLUNTARIO_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS roles_voluntario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voluntario_id UUID NOT NULL REFERENCES voluntarios(id),
    tipo_rol TEXT NOT NULL CHECK (tipo_rol IN ('intake', 'seguimiento', 'acogida', 'salud')),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (voluntario_id, tipo_rol)
)
"""

# --- eventos_ciclo_vida_animal (issue #68) -------------------------------
# Log append-only de las transiciones del ciclo de vida del animal. Cada
# evento registra que el animal paso por un estado (entrada, acogida,
# adopcion, muerte, etc.). Es la fuente de verdad del estado: la tabla
# ``estado_actual_animal`` es solo un cache materializado que se
# reconstruye a partir de aqui.
#
# 13 columnas (snake_case espanol, decision #13454: como esta tabla NO
# existe en el legacy, no hay columnas heredadas CamelCase — todo es
# espanol). FKs: animal_id -> animales, evento_causa_id -> self (cadena
# causal ADOPTDEVUELTA), creado_por -> usuarios_autorizados (NO 'usuarios'
# generico, esa tabla no existe en el schema actual).

EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS eventos_ciclo_vida_animal (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    tipo_evento VARCHAR(50) NOT NULL CHECK (tipo_evento IN (
        'INTAKE_STARTED',
        'INTAKE_COMPLETED',
        'INTAKE_REOPENED',
        'FOSTER_STARTED',
        'FOSTER_CLOSED_BY_ADOPTION',
        'FOSTER_RETURNED',
        'FOSTER_REOPENED',
        'ADOPTION_STARTED',
        'ADOPTION_RETURNED',
        'ADOPTION_REOPENED',
        'OWNER_RETURNED',
        'DEATH_RECORDED',
        'STATE_CORRECTION'
    )),
    fecha_evento TIMESTAMPTZ NOT NULL,
    evento_causa_id UUID REFERENCES eventos_ciclo_vida_animal(id),
    tabla_origen_legacy VARCHAR(50),
    id_origen_legacy INTEGER,
    fuente_entidad_tipo VARCHAR(30),
    fuente_entidad_id UUID,
    metadatos JSONB,
    creado_por UUID NOT NULL REFERENCES usuarios_autorizados(id),
    fecha_creacion TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

# --- estado_actual_animal (issue #69) -------------------------------------
# Cache materializado del estado actual del animal. Una fila por animal
# (animal_id es PK). Se reconstruye desde eventos_ciclo_vida_animal.
#
# 10 columnas (snake_case espanol). NO incluye ``estado_previo_muerte``
# porque el dato ya existe en ``animales.UltimoEstadoAntesDeFallecido``
# (CamelCase legacy, ya migrado) — duplicar seria redundancia y abre la
# puerta a drift entre dos copias. JOIN a animales cuando se necesite.

ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS estado_actual_animal (
    animal_id UUID PRIMARY KEY REFERENCES animales(id),
    situacion_actual VARCHAR(50) NOT NULL CHECK (
        situacion_actual IN (
            'Pendiente de Entrada',
            'Pendiente de Nueva Situacion',
            'Albergue',
            'Acogida',
            'Adoptado',
            'Entregado',
            'Incoherente'
        )
        OR situacion_actual LIKE 'Fallecido (%)'
    ),
    evento_activo_id UUID REFERENCES eventos_ciclo_vida_animal(id),
    intake_activo_id UUID,
    foster_activo_id UUID,
    adopcion_activa_id UUID,
    fecha_cambio_estado TIMESTAMPTZ NOT NULL,
    situacion_legacy VARCHAR(100),
    estado_reconciliacion VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (
        estado_reconciliacion IN ('pending', 'matched', 'divergent', 'migrated')
    ),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

# --- indices (separados, no multi-statement, defensivo) ------------------
# ``InsForge /api/database/advance/rawsql`` es un wrapper thin de
# PostgreSQL; multi-statement no probado. Cada CREATE INDEX vive en su
# propia constante y se ejecuta en una llamada separada.

# eventos_ciclo_vida_animal: 4 indices
EVENTOS_CICLO_VIDA_ANIMAL_IDX_ANIMAL_FECHA = """
CREATE INDEX IF NOT EXISTS idx_eventos_ciclo_vida_animal_animal_fecha
    ON eventos_ciclo_vida_animal (animal_id, fecha_evento DESC)
"""

EVENTOS_CICLO_VIDA_ANIMAL_IDX_TIPO = """
CREATE INDEX IF NOT EXISTS idx_eventos_ciclo_vida_animal_tipo
    ON eventos_ciclo_vida_animal (tipo_evento)
"""

EVENTOS_CICLO_VIDA_ANIMAL_IDX_LEGACY = """
CREATE INDEX IF NOT EXISTS idx_eventos_ciclo_vida_animal_legacy
    ON eventos_ciclo_vida_animal (tabla_origen_legacy, id_origen_legacy)
"""

EVENTOS_CICLO_VIDA_ANIMAL_IDX_CAUSA = """
CREATE INDEX IF NOT EXISTS idx_eventos_ciclo_vida_animal_causa
    ON eventos_ciclo_vida_animal (evento_causa_id)
"""

# estado_actual_animal: 2 indices
ESTADO_ACTUAL_ANIMAL_IDX_SITUACION = """
CREATE INDEX IF NOT EXISTS idx_estado_actual_animal_situacion
    ON estado_actual_animal (situacion_actual)
"""

ESTADO_ACTUAL_ANIMAL_IDX_RECONCILIACION = """
CREATE INDEX IF NOT EXISTS idx_estado_actual_animal_reconciliacion
    ON estado_actual_animal (estado_reconciliacion)
"""


def ensure_domain_schema(client: InsForgeClient) -> None:
    """Create the domain tables (idempotent) in dependency order.

    Orden estricto por FKs:

    - ``animales``: independiente, va primero (tabla mas escrita).
    - ``voluntarios``: independiente de animales, va segundo.
    - ``roles_voluntario``: FK a voluntarios, va tercero.
    - ``eventos_ciclo_vida_animal``: FK a animales + self, va cuarto
      (necesita animales ya creada).
    - ``estado_actual_animal``: FK a animales + eventos_ciclo_vida_animal,
      va quinto (necesita ambas creadas).

    Despues de las 5 tablas, se ejecutan los 6 CREATE INDEX
    (``IF NOT EXISTS``) para los queries criticos del dashboard
    (situacion_actual, estado_reconciliacion) y del timeline
    (animal_id + fecha_evento, tipo_evento, lookup legacy, cadena causal).

    Total: 5 CREATE TABLE + 6 CREATE INDEX = 11 calls.
    Idempotente: re-ejecucion es segura (``IF NOT EXISTS`` en todos).
    """
    # 5 tablas en orden de dependencia FK
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTARIOS_CREATE_TABLE_SQL)
    client.execute_sql(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL)
    client.execute_sql(ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL)

    # 6 indices (cada uno en su propia constante defensivamente)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_ANIMAL_FECHA)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_TIPO)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_LEGACY)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_CAUSA)
    client.execute_sql(ESTADO_ACTUAL_ANIMAL_IDX_SITUACION)
    client.execute_sql(ESTADO_ACTUAL_ANIMAL_IDX_RECONCILIACION)