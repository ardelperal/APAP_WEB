"""Domain schema bootstrap: animals, voluntarios, roles_voluntario,
entradas, acogidas, adopciones.

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
- The schema is intentionally minimal: no triggers, no extra indices
  beyond what the constraints imply, no related tables
  (animal_event_log, attachments, etc.) — those come in later cycles
  (LIFECYCLE-SCHEMA-02, DOC-01..04).
- ``entradas``, ``acogidas`` and ``adopciones`` form the LIFECYCLE-03
  minimal surface needed for the bidirectional migration; their FK
  chain mirrors the legacy workflow (intake -> foster or adoption).
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

# --- entradas: TbEntradas (14 cols) + mejoras justificadas ---
#
# LIFECYCLE-03 (migration-01). Migration target of TbEntradas from the
# legacy Access production DB. FKs to animales and voluntarios. The
# natural-key UNIQUE constraint on (animal_id, fecha_entrada) prevents
# duplicate intakes for the same animal on the same day.

ENTRADAS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS entradas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    voluntario_entrada_id UUID REFERENCES voluntarios(id),
    voluntario_salida_id UUID REFERENCES voluntarios(id),
    fecha_entrada DATE NOT NULL,
    fecha_salida DATE,
    fecha_entrega_propietario DATE,
    origen TEXT,
    motivo TEXT,
    donativo_entregador NUMERIC(10,2),
    observaciones TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT entradas_natural_key UNIQUE (animal_id, fecha_entrada)
)
"""

# --- acogidas: TbAcogidaAnimal (15 cols) + mejoras justificadas ---
#
# LIFECYCLE-03 (migration-01). FKs to animales, voluntarios and entradas
# (the entry that originated this foster placement).

ACOGIDAS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS acogidas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    voluntario_acogida_id UUID REFERENCES voluntarios(id),
    voluntario_seguimiento1_id UUID REFERENCES voluntarios(id),
    voluntario_seguimiento2_id UUID REFERENCES voluntarios(id),
    voluntario_sanitario_id UUID REFERENCES voluntarios(id),
    fecha_inicio DATE NOT NULL,
    fecha_final DATE,
    entrada_origen_id UUID REFERENCES entradas(id),
    direccion TEXT,
    telefono TEXT,
    observaciones TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT acogidas_natural_key UNIQUE (animal_id, fecha_inicio)
)
"""

# --- adopciones: TbAdopcion (16 cols) + mejoras justificadas ---
#
# LIFECYCLE-03 (migration-01). FKs to animales, voluntarios and entradas
# (the entry that originated this adoption). ``nombre_adoptante`` is
# the only mandatory adoptante field because the legacy contract treats
# it as the canonical contact name; dni/telefono/email are optional.

ADOPCIONES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS adopciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    voluntario_seguimiento_id UUID REFERENCES voluntarios(id),
    fecha_adopcion DATE NOT NULL,
    fecha_devolucion DATE,
    donativo_preadopcion NUMERIC(10,2),
    donativo_adopcion NUMERIC(10,2),
    nombre_adoptante TEXT NOT NULL,
    dni_adoptante TEXT,
    telefono_adoptante TEXT,
    email_adoptante TEXT,
    entrada_origen_id UUID REFERENCES entradas(id),
    observaciones TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT adopciones_natural_key UNIQUE (animal_id, fecha_adopcion)
)
"""

# --- animal_lifecycle_events (LIFECYCLE-SCHEMA-02, web-only-feature-preservation PR 1) ---
#
# P0 BLOCKER for PR 2 (derivation engine + semantic events). Append-only
# event log: every lifecycle transition writes one row here. The
# derivation engine re-derives the animal's current state from this log
# on every legacy write. Schema mirrors
# docs/discovery/lifecycle-event-log-design.md §3.1 verbatim — column
# names, types, FK targets and CHECK enum are the contract. Spec:
# openspec/changes/web-only-feature-preservation/specs/.../spec.md
# REQ-Capa Semantica de Eventos.

ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animal_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    event_type VARCHAR(50) NOT NULL CHECK (event_type IN (
        'INTAKE_STARTED', 'INTAKE_COMPLETED',
        'FOSTER_STARTED', 'FOSTER_RETURNED', 'FOSTER_CLOSED_BY_ADOPTION',
        'ADOPTION_STARTED', 'ADOPTION_RETURNED',
        'OWNER_RETURNED', 'DEATH_RECORDED',
        'STATE_CORRECTION',
        'CHIP_CHANGED', 'INTAKE_REOPENED', 'FOSTER_REOPENED', 'ADOPTION_REOPENED'
    )),
    event_timestamp TIMESTAMPTZ NOT NULL,
    caused_by_event_id UUID REFERENCES animal_lifecycle_events(id),
    source_entity_type VARCHAR(30),
    source_entity_id UUID,
    legacy_source_table VARCHAR(50),
    legacy_source_id INTEGER,
    metadata JSONB,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

# --- animal_current_state (LIFECYCLE-SCHEMA-02, web-only-feature-preservation PR 1) ---
#
# Materialized cache of the derived state per animal. Rebuilt from
# ``animal_lifecycle_events`` on every legacy write; never manually
# mutated (admin overrides go via STATE_CORRECTION events, design
# §3.2). The PK is ``animal_id`` (1:1 with ``animales``) — there is no
# separate surrogate id, by design. Schema per
# docs/discovery/lifecycle-event-log-design.md §3.2.

ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animal_current_state (
    animal_id UUID PRIMARY KEY REFERENCES animales(id),
    current_state VARCHAR(50) NOT NULL CHECK (current_state IN (
        'Pendiente de Entrada',
        'Pendiente de Nueva Situación',
        'Albergue', 'Acogida', 'Adoptado',
        'Entregado',
        'Fallecido (Albergue)', 'Fallecido (Acogida)',
        'Fallecido (Adoptado)', 'Fallecido (Entregado)',
        'Fallecido (Desconocido)',
        'Incoherente'
    )),
    active_event_id UUID REFERENCES animal_lifecycle_events(id),
    active_intake_id UUID,
    active_foster_id UUID,
    active_adoption_id UUID,
    pre_death_state VARCHAR(50),
    state_changed_at TIMESTAMPTZ NOT NULL,
    legacy_situacion VARCHAR(100),
    legacy_ultimo_estado VARCHAR(50),
    reconciliation_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (reconciliation_status IN ('matched', 'divergent', 'migrated', 'pending'))
)
"""


def ensure_domain_schema(client: InsForgeClient) -> None:
    """Create the domain tables (idempotent) in dependency order.

    Order respects FK dependencies:

    1. ``animales`` and ``voluntarios`` are independent roots.
    2. ``roles_voluntario`` depends on ``voluntarios``.
    3. ``entradas`` depends on ``animales`` and ``voluntarios``.
    4. ``acogidas`` depends on ``animales``, ``voluntarios`` and ``entradas``.
    5. ``adopciones`` depends on ``animales``, ``voluntarios`` and ``entradas``.
    6. ``animal_lifecycle_events`` depends on ``animales`` (event log).
    7. ``animal_current_state`` depends on ``animales`` and the event log.

    Any other order means a foreign-key will fail on a clean database.
    The two new tables are PR 1 of ``web-only-feature-preservation``;
    they are P0 BLOCKERS for PR 2 (derivation engine + semantic events).
    """
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTARIOS_CREATE_TABLE_SQL)
    client.execute_sql(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
    client.execute_sql(ENTRADAS_CREATE_TABLE_SQL)
    client.execute_sql(ACOGIDAS_CREATE_TABLE_SQL)
    client.execute_sql(ADOPCIONES_CREATE_TABLE_SQL)
    client.execute_sql(ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL)
    client.execute_sql(ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL)
