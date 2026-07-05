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

# --- entradas: migration-compatible physical schema (#87) ---
#
# Accepted web CRUD/service/form surface for intake entries stays minimal:
# intake volunteer, intake date, source/motive/notes, soft-delete, and
# timestamps. The physical table also keeps nullable salida/entrega/donativo
# columns that entrada.yaml maps from legacy data. Those fields are migration
# compatibility columns and remain deferred from the public CRUD contract until
# a dedicated workflow slice exposes them. The natural-key UNIQUE constraint on
# (animal_id, fecha_entrada) prevents duplicate intakes for the same animal on
# the same day.

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
    observaciones TEXT,
    donativo_entregador NUMERIC(10,2),
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

# --- casas_acogida: TbAcogidaCasas (19 cols legacy) + 2 mejoras justificadas
# (FOSTER-01, #43) ------------------------------------------------------------
#
# Casa de Acogida is a separate entity from the foster stay (``acogidas``
# below). Legacy keeps ``TbAcogidaCasas`` and ``TbAcogidaAnimal`` as
# distinct tables so a single house can host multiple stays over time.
# The new application mirrors that split.
#
# Justified improvements vs legacy (P1 fidelity D-FOSTER-02):
# - ``id`` UUID PK (legacy uses ``IDAcogidaCasa`` INT) — stable, portable FK
#   target. FOSTER-02 will add ``acogidas.casa_acogida_id REFERENCES
#   casas_acogida(id)``.
# - ``capacidad`` INTEGER NOT NULL CHECK (capacidad > 0) — legacy has no
#   capacity column. Discovery 2.2 documents it as a rule; without it
#   FOSTER-03 (gate de capacidad) cannot be implemented.
#
# P1 fidelity: 19 legacy columns preserved 1:1, including the Spanish
# tilde in ``coche = 'Sí' / 'No'`` (mirrors ``cesiones_propietario`` CHECK
# pattern). ``activo`` + ``fecha_baja`` soft-delete (project-wide
# convention).

CASAS_ACOGIDA_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS casas_acogida (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    apellidos TEXT NOT NULL,
    dni_acogedor TEXT,
    calle TEXT NOT NULL,
    numero TEXT,
    piso TEXT,
    letra TEXT,
    localidad TEXT,
    provincia TEXT,
    cp TEXT,
    telefono TEXT NOT NULL,
    telefono2 TEXT,
    email TEXT,
    vinculacion TEXT,
    caracteristicas TEXT,
    coche TEXT NOT NULL CHECK (coche IN ('Sí', 'No')),
    especie_preferente TEXT CHECK (
        especie_preferente IS NULL
        OR especie_preferente IN ('CANINA', 'FELINA')
    ),
    observaciones TEXT,
    capacidad INTEGER NOT NULL CHECK (capacidad > 0),
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    fecha_baja TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

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

# FOSTER-02 (#44) — añade la FK estructurada desde ``acogidas`` hacia la
# entidad ``casas_acogida`` creada por FOSTER-01 (#43). La columna es
# opcional (NULL permitida) para preservar la retro-compatibilidad con
# estancias históricas que no tienen casa asignada (D-EST-01). El patrón
# ``ADD COLUMN IF NOT EXISTS`` es idempotente: re-ejecutar
# ``ensure_domain_schema`` no falla ni duplica la columna.
#
# Justificación de usar ALTER TABLE en lugar de añadir la columna al
# ``ACOGIDAS_CREATE_TABLE_SQL`` directamente (D-EST-05): el diff entre
# FOSTER-01 y FOSTER-02 muestra el cambio explícitamente; el
# ``CREATE TABLE`` permanece congelado (tests existentes en
# ``tests/test_domain.py`` no necesitan actualizarse); futuras columnas
# a ``acogidas`` (FOSTER-03+) replican este patrón sin alterar el
# ``CREATE TABLE`` original.
ACOGIDAS_ADD_CASA_FK_SQL = """
ALTER TABLE acogidas
ADD COLUMN IF NOT EXISTS casa_acogida_id UUID REFERENCES casas_acogida(id)
"""

# --- foster_capacity_overrides: FOSTER-03 (#45) -----------------------------
#
# Audit log para los overrides de capacidad que el operador registra cuando
# acepta asignar un animal a una casa que ya excede ``capacidad`` (con su
# especie preferida). Una fila por override; nunca se borra. El gate de
# especie (D-GC-01, FOSTER-03) NO genera override — es hard block sin
# anulación. Solo el capacity advisory produce filas aquí.
#
# Decisión D-GC-01: tabla propia (no reusar ``animal_lifecycle_events``).
# Justificación en ``openspec/changes/foster-gate-capacidad/proposal.md``
# §D-GC-01 — la query "dame todos los overrides de esta casa" es indexable
# trivialmente con un BTREE en ``casa_acogida_id``, y mezclar eventos del
# animal con auditoría de capacidad introduce ambigüedad en la deducción
# futura del state machine (PR 2 de ``web-only-feature-preservation``).
#
# ``operador_user_id`` referencia ``usuarios_autorizados(id)`` pero NO
# declaramos la FK porque esa tabla la crea ``ensure_schema_and_seed``
# ANTES de ``ensure_domain_schema``; para evitar un ordenamiento frágil
# adicional, lo dejamos como UUID libre. La integridad referencial se
# garantiza a nivel de aplicación: el handler extrae ``user_id`` de la
# sesión y nunca acepta input del usuario en ese campo.
#
# ``motivo`` es TEXT NOT NULL — la validación de non-empty vive en el
# service (``record_override``); el constraint es el cinturón de
# seguridad por si un INSERT crudo intenta meter una fila vacía.
FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS foster_capacity_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    casa_acogida_id UUID NOT NULL REFERENCES casas_acogida(id),
    animal_id UUID NOT NULL REFERENCES animales(id),
    operador_user_id UUID NOT NULL,
    motivo TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

# Issue #142 — añade la FK opcional hacia ``acogidas`` para que cada
# override pueda enlazarse con la estancia que justificó. La columna es
# NULLable: el INSERT inicial la deja en NULL (el operador puede
# cancelar el create de la estancia y la auditoría queda honesta
# porque se puede consultar el residuo via
# ``SELECT * FROM foster_capacity_overrides WHERE estancia_id IS NULL``).
# ``create_acogida`` (``app/modules/acogidas/service.py``) emite el
# UPDATE que enlaza el row una vez la estancia es creada; el
# ``AND estancia_id IS NULL`` del WHERE protege contra un link duplicado.
# Idempotente (``ADD COLUMN IF NOT EXISTS``) para que el bootstrap se
# pueda re-aplicar sin crash.
FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL = """
ALTER TABLE foster_capacity_overrides
ADD COLUMN IF NOT EXISTS estancia_id UUID NULL REFERENCES acogidas(id)
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT animal_lifecycle_events_natural_key UNIQUE (animal_id, event_type, event_timestamp)
)
"""
# Natural-key UNIQUE on (animal_id, event_type, event_timestamp) is what
# makes the ``animal_lifecycle_events`` INSERT idempotent: a retry of
# the same logical event (same animal + same event_type + same
# event_timestamp) collapses to a single row. The persister uses
# ``INSERT ... ON CONFLICT (animal_id, event_type, event_timestamp)
# DO NOTHING`` (PostgreSQL/InsForge syntax) so a retry apply after a
# post-COMMIT failure does NOT create a duplicate row that would
# double-count the transition in the animal state machine. The
# constraint + DO NOTHING combo is the DB-level idempotence guard
# (PR 4 follow-up, P1 #2).

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

# --- cesiones_propietario (TbCesionPorPropietario legacy, issue #41) ---
#
# Owner-surrender (Cesión por Propietario) workflow. 19 legacy columns
# from ``TbCesionPorPropietario`` preserved 1:1 per the P1 fidelity
# invariant (``docs/proceso.md`` §0). 11 records in production as of
# 2026-07-03, verified via Dysflow MCP (projectId=apap, backendPath=
# Registro_APAP_Alcala_datos_18.accdb). Legacy PK = IDEntrada (FK to
# entradas), enforced 1-a-1 with UNIQUE on entrada_id.
#
# Decisions vs the legacy schema:
# - ``numero_contrato`` legacy format was "CP" + 4 digits (CP0671,
#   CP0257, ...). Web accepts any non-empty string (auto-generation TBD).
# - ``cartilla_sanitaria`` / ``certificado_veterinario`` /
#   ``autorizacion_recogida`` stored as TEXT (legacy "Sí"/"No" with
#   Spanish tilde) rather than BOOLEAN to preserve original operator
#   vocabulary and round-trip cleanly with legacy exports.
# - ``hora_cesion`` stored as TIMESTAMP (legacy Date/Time); accepts
#   date-only or full timestamp input.
# - ``nombre_representante`` is NOT NULL here (legacy nullable in
#   table DDL but mandatory at the product level — no surrender
#   without an owner). Documented gap, see docs/decisiones-proyecto.md.
CESIONES_PROPIETARIO_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cesiones_propietario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entrada_id UUID NOT NULL UNIQUE REFERENCES entradas(id),
    numero_contrato TEXT NOT NULL,
    nombre_representante TEXT NOT NULL,
    cartilla_sanitaria TEXT CHECK (
        cartilla_sanitaria IS NULL
        OR cartilla_sanitaria IN ('Sí', 'No')
    ),
    certificado_veterinario TEXT CHECK (
        certificado_veterinario IS NULL
        OR certificado_veterinario IN ('Sí', 'No')
    ),
    autorizacion_recogida TEXT CHECK (
        autorizacion_recogida IS NULL
        OR autorizacion_recogida IN ('Sí', 'No')
    ),
    fecha_vacuna_rabia DATE,
    numero_colegiado TEXT,
    numero_colaborador TEXT,
    dni_representante TEXT,
    calle_representante TEXT,
    numero_calle_representante TEXT,
    piso_representante TEXT,
    letra_representante TEXT,
    localidad_representante TEXT,
    provincia_representante TEXT,
    cp_representante TEXT,
    telefono_representante TEXT,
    email_representante TEXT,
    hora_cesion TIMESTAMP,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

# --- entradas_batch_staging: INTAKE-02 (Entradas Múltiples, legacy
# ``TbEntradasMultiplesAuxIniciales``) ------------------------------------
#
# Staging table for batch intake entries (issue #40). Persists each
# record between the staging request and the commit, mirroring the
# legacy "aux inicial" pre-commit pattern so the operator can preview
# and cancel without committing. ``sequence`` preserves the operator's
# input order; ``batch_id`` groups rows from one staging request.
# Atomic commit copies the rows to ``entradas`` via a single CTE
# statement (see ``app/modules/entradas/batch_service.py::commit_batch``);
# the copy and the staging cleanup happen in the same statement so a
# failure during the copy leaves staging intact for diagnosis.

ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS entradas_batch_staging (
    batch_id UUID NOT NULL,
    sequence INTEGER NOT NULL,
    animal_id UUID NOT NULL,
    voluntario_entrada_id UUID,
    fecha_entrada DATE NOT NULL,
    origen TEXT,
    motivo TEXT,
    observaciones TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, sequence)
)
"""

# --- contratos (modelo polimórfico Fase 7) --------------------------------
#
# Contract metadata for every workflow that generates one (entrada,
# acogida, adopcion, cesión por propietario). Legacy
# ``TbContratosAnexos`` was already polymorphic (IDEntrada + IDAcogida
# + IDAdopcion nullable). Web keeps the shape and ADDS
# ``tipo_contrato_id`` FK to ``catalogos_tipos_contrato`` (CATALOG-01)
# so each row carries its type explicitly — the legacy
# ``TbPlantillas`` join was brittle (queried by template name string).
# ``contratos_exactly_one_entity`` CHECK enforces that the row
# references exactly one of the four entity FKs.
CONTRATOS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS contratos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo_contrato_id UUID NOT NULL REFERENCES catalogos_tipos_contrato(id),
    numero_contrato TEXT NOT NULL,
    fecha DATE NOT NULL,
    entrada_id UUID REFERENCES entradas(id),
    acogida_id UUID REFERENCES acogidas(id),
    adopcion_id UUID REFERENCES adopciones(id),
    cesion_id UUID REFERENCES cesiones_propietario(id),
    nombre_archivo TEXT,
    observaciones TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT contratos_exactly_one_entity CHECK (
        (CASE WHEN entrada_id IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN acogida_id IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN adopcion_id IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN cesion_id IS NOT NULL THEN 1 ELSE 0 END) = 1
    )
)
"""


# --- actuacion_sanitaria: HEALTH-01 (#50) — historial clinico por animal --
#
# Tabla nueva modelada como ``TbActuacionSanitaria`` legacy, separada del
# animal (``animales``) y de la estancia (``acogidas``). Permite a APAP
# registrar el historial veterinario de cada animal (vacunas, desparasita-
# ciones, esterilizaciones, analiticas) preservando la fecha del acto, el
# tipo referenciado al catalogo de pruebas (CATALOG-01 #65), el veterina-
# rio, el voluntario responsable y observaciones libres.
#
# FKs:
# - ``animal_id`` → ``animales(id)`` (NOT NULL, activo=true enforced en CTE).
# - ``tipo_actuacion_id`` → ``catalogos_pruebas(id)`` (NULL permitido, D-HEALTH-01).
# - ``voluntario_id`` → ``voluntarios(id)`` (NULL permitido, activo=true
#   enforced en CTE per VOL-05).
#
# El ``tipo_actuacion_id`` referencia ``catalogos_pruebas`` (issue #65
# CATALOG-01). El lifespan ejecuta ``ensure_catalogs`` ANTES de
# ``ensure_domain_schema`` para que las tablas de catalogo existan en un
# backend limpio antes de crear las FKs de dominio. Dentro de
# ``ensure_domain_schema`` esta tabla sigue al final, despues de
# ``contratos``, porque ``animales`` y ``voluntarios`` ya existen por
# entonces. La regla D-24
# (validacion de fechas) NO se enforce en el schema — vive en la capa de
# service (``app/modules/sanidad/service.py::_validate_fecha_d24`` +
# CTE ``_INSERT_ACTUACION_SANITARIA_SQL``).
ACTUACION_SANITARIA_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS actuacion_sanitaria (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    fecha DATE NOT NULL,
    tipo_actuacion_id UUID REFERENCES catalogos_pruebas(id),
    veterinario TEXT,
    observaciones TEXT,
    voluntario_id UUID REFERENCES voluntarios(id),
    material_utilizado TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
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
    8. ``cesiones_propietario`` depends on ``entradas`` (FK UNIQUE).
    9. ``contratos`` FKs to ``entradas``, ``acogidas``, ``adopciones``,
       ``cesiones_propietario`` AND ``catalogos_tipos_contrato``. The
       catalog FK requires ``ensure_catalogs`` (in ``app.main::lifespan``)
       to have run BEFORE ``ensure_domain_schema``.
       The two contract-table FKs sit at the END so all entity tables
       they reference exist before contratos builds.
    10. ``actuacion_sanitaria`` (HEALTH-01 #50) FKs to ``animales``,
        ``catalogos_pruebas`` (CATALOG-01 #65) and ``voluntarios``. Placed
        LAST because the domain tables it references are roots and the
        catalog tables are already created by the lifespan. See
        ``app/modules/sanidad/service.py`` for the D-24 date validation rule.

    The two new tables are PR 1 of ``web-only-feature-preservation``;
    they are P0 BLOCKERS for PR 2 (derivation engine + semantic events).
    """
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTARIOS_CREATE_TABLE_SQL)
    client.execute_sql(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
    client.execute_sql(ENTRADAS_CREATE_TABLE_SQL)
    client.execute_sql(ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL)
    client.execute_sql(CASAS_ACOGIDA_CREATE_TABLE_SQL)
    client.execute_sql(ACOGIDAS_CREATE_TABLE_SQL)
    # FOSTER-02 (#44) — añade la FK estructurada desde ``acogidas`` hacia
    # ``casas_acogida``. Idempotente (``ADD COLUMN IF NOT EXISTS``) y
    # emitido DESPUÉS del CREATE TABLE de acogidas para garantizar que
    # la tabla referenciada (``casas_acogida``) ya existe en la base.
    client.execute_sql(ACOGIDAS_ADD_CASA_FK_SQL)
    # FOSTER-03 (#45) — audit log para los overrides de capacidad. La
    # tabla referencia ``casas_acogida`` y ``animales``, ambas ya
    # creadas; emisión DESPUÉS del ALTER de ``acogidas`` mantiene el
    # orden lógico del slice foster. Idempotente vía
    # ``CREATE TABLE IF NOT EXISTS``.
    client.execute_sql(FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL)
    # Issue #142 — añade la FK opcional ``estancia_id`` al audit log.
    # Emisión DESPUÉS del CREATE de ``foster_capacity_overrides`` (para
    # que la tabla target exista) y DESPUÉS del CREATE de ``acogidas``
    # (para que el FK target exista). Idempotente vía ``ADD COLUMN IF
    # NOT EXISTS``; ver el docstring del SQL constant para el contrato
    # completo del fix y la query de auditoría de huérfanos.
    client.execute_sql(FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL)
    client.execute_sql(ADOPCIONES_CREATE_TABLE_SQL)
    client.execute_sql(ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL)
    client.execute_sql(ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL)
    client.execute_sql(CESIONES_PROPIETARIO_CREATE_TABLE_SQL)
    client.execute_sql(CONTRATOS_CREATE_TABLE_SQL)
    # HEALTH-01 (#50) — historial clinico por animal. Ver bloque de doc
    # arriba; emite DESPUES de contratos porque las tablas de dominio que
    # referencia ya estan creadas y el lifespan ya creo los catalogos.
    # ``CREATE TABLE IF NOT EXISTS`` lo hace idempotente entre reinicios.
    client.execute_sql(ACTUACION_SANITARIA_CREATE_TABLE_SQL)
