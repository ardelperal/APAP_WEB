"""Domain schema bootstrap: animals, voluntarios, roles_voluntario.

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
- The schema is intentionally minimal in this first slice: no triggers,
  no extra indices beyond what the constraints imply, no related tables
  (animal_event_log, attachments, etc.) — those come in later cycles
  (LIFECYCLE-SCHEMA-02, DOC-01..04).
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


def ensure_domain_schema(client: InsForgeClient) -> None:
    """Create the domain tables (idempotent) in dependency order.

    Order matters: ``roles_voluntario`` has a foreign key to
    ``voluntarios``, so the parent table must be created first. ``animales``
    is independent of the other two and is created first for symmetry
    (most-frequently-written table at the top of the migration).
    """
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTARIOS_CREATE_TABLE_SQL)
    client.execute_sql(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
