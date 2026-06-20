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


def ensure_domain_schema(client: InsForgeClient) -> None:
    """Create the domain tables (idempotent) in dependency order.

    Order respects FK dependencies:

    1. ``animales`` and ``voluntarios`` are independent roots.
    2. ``roles_voluntario`` depends on ``voluntarios``.
    3. ``entradas`` depends on ``animales`` and ``voluntarios``.
    4. ``acogidas`` depends on ``animales``, ``voluntarios`` and ``entradas``.
    5. ``adopciones`` depends on ``animales``, ``voluntarios`` and ``entradas``.

    Any other order means a foreign-key will fail on a clean database.
    """
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTARIOS_CREATE_TABLE_SQL)
    client.execute_sql(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
    client.execute_sql(ENTRADAS_CREATE_TABLE_SQL)
    client.execute_sql(ACOGIDAS_CREATE_TABLE_SQL)
    client.execute_sql(ADOPCIONES_CREATE_TABLE_SQL)
