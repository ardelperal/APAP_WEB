"""Catalog (reference data) schema + seed for APAP_WEB (issue #65 CATALOG-01).

Source of truth: Microsoft Access legacy database ``Registro_APAP_Alcala_datos_18.accdb``
under ``C:\\00repos\\codigo\\APAP_ACTUAL\\``. Values were extracted via
Dysflow MCP on 2026-07-03 (counts verified against the Access file):
``TbOrigenEntrada`` -> 7 rows, ``TbMotivosEntrada`` -> 21 rows,
``TbNombrePruebas`` -> 13 rows, ``TbPruebasPeridicidad`` -> 12 rows,
``TbPlantillas`` -> 8 rows.

If the legacy values change, regenerate the seed here AND verify the
deltas still match the Access file (P1 fidelity premise in
``docs/proceso.md`` §0).

**P1 fidelity note (2026-07-03)**: Dysflow reports the legacy string
columns with mojibake (Accent characters come back as ``\\ufffd``) because
the legacy .accdb is stored in Windows-1252 and Dysflow decodes the
bytes as UTF-8. The seed below restores the proper Spanish spelling —
the original Spanish text the legacy intends — rather than copy the
byte corruption verbatim. The byte-level mojibake is a legacy storage
artifact, not a domain fact.

**Coexistence / bidirectional sync**: ``docs/roadmap.md`` §3 Fase 7
will wire the migration framework's ``reconcile.py`` to push catalog
deltas from web -> legacy and from legacy -> web. Until then, the seed
is the one-shot bootstrap; any in-app CR(U)D on these catalogs is
scoped to the period of unaided coexistence.

**Idempotence contract**: ``ensure_catalogs`` is safe to call on every
cold start. ``CREATE TABLE IF NOT EXISTS`` is a no-op when the table
already exists; ``INSERT ... ON CONFLICT (...) DO NOTHING`` collapses
a duplicate INSERT into a single row. A second call therefore
produces no observable state change.
"""

from __future__ import annotations

from typing import Any

from app.core.insforge import InsForgeClient
from app.core.schema_bootstrap import SqlStatement, run_idempotent_sql

# --- catalogos_origenes (7 rows from TbOrigenEntrada) --------------------
#
# The legacy has a single column ``Origen`` of TEXT. Each row becomes one
# catalog row whose ``codigo`` equals the legacy ``Origen`` verbatim
# (Spanish spelling restored, see module docstring).


CATALOGOS_ORIGENES_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS catalogos_origenes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

CATALOGOS_ORIGENES_SEED_SQL = """
INSERT INTO catalogos_origenes (codigo, nombre, orden)
VALUES
    ('Acogida', 'Acogida', 1),
    ('Adopción', 'Adopción', 2),
    ('Camada', 'Camada', 3),
    ('Compra', 'Compra', 4),
    ('otros', 'Otros', 5),
    ('Recogido de la calle', 'Recogido de la calle', 6),
    ('Regalo', 'Regalo', 7)
ON CONFLICT (codigo) DO NOTHING
"""

LIST_CATALOGOS_ORIGENES_SQL = """
SELECT id, codigo, nombre, descripcion, activo, orden
FROM catalogos_origenes
WHERE activo = true
ORDER BY orden NULLS LAST, codigo
"""


# --- catalogos_motivos (21 rows from TbMotivosEntrada) --------------------
#
# The legacy natural key is (Motivo, Especie). The catalog mirrors that
# exactly so legacy rows map 1:1 into the catalog. The single FELINA-only
# motivo ("De colonia de gatos") is preserved with its Especie.


CATALOGOS_MOTIVOS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS catalogos_motivos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    especie TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT catalogos_motivos_natural_key UNIQUE (codigo, especie)
)
"""

CATALOGOS_MOTIVOS_SEED_SQL = """
INSERT INTO catalogos_motivos (codigo, nombre, especie, orden)
VALUES
    ('Abandono', 'Abandono', 'AMBOS', 1),
    ('Agresividad', 'Agresividad', 'AMBOS', 2),
    ('Alergia', 'Alergia', 'AMBOS', 3),
    ('Camada que no consigue colocar', 'Camada que no consigue colocar', 'AMBOS', 4),
    ('Cambio de domicilio', 'Cambio de domicilio', 'AMBOS', 5),
    ('De colonia de gatos', 'De colonia de gatos', 'FELINA', 6),
    ('Desalojo (hacinamiento)', 'Desalojo (hacinamiento)', 'AMBOS', 7),
    ('Enfermedad del propietario', 'Enfermedad del propietario', 'AMBOS', 8),
    ('Entregados por otra Asociación', 'Entregados por otra Asociación', 'AMBOS', 9),
    ('Inadaptación', 'Inadaptación', 'AMBOS', 10),
    ('Lo sacó de perrera para evitar su sacrificio', 'Lo sacó de perrera para evitar su sacrificio', 'AMBOS', 11),
    ('Maltrato', 'Maltrato', 'AMBOS', 12),
    ('Motivos desconocidos', 'Motivos desconocidos', 'AMBOS', 13),
    ('Muerte propietario', 'Muerte propietario', 'AMBOS', 14),
    ('No se puede hacer cargo', 'No se puede hacer cargo', 'AMBOS', 15),
    ('Recogido en la calle', 'Recogido en la calle', 'AMBOS', 16),
    ('Regalo no deseado', 'Regalo no deseado', 'AMBOS', 17),
    ('Rescate', 'Rescate', 'AMBOS', 18),
    ('Retirado por la Asociación (malas condiciones)', 'Retirado por la Asociación (malas condiciones)', 'AMBOS', 19),
    ('Se han cansado del animal', 'Se han cansado del animal', 'AMBOS', 20),
    ('Separación', 'Separación', 'AMBOS', 21)
ON CONFLICT (codigo, especie) DO NOTHING
"""

LIST_CATALOGOS_MOTIVOS_SQL = """
SELECT id, codigo, nombre, especie, activo, orden
FROM catalogos_motivos
WHERE activo = true
ORDER BY orden NULLS LAST, especie, codigo
"""


# --- catalogos_pruebas (13 rows from TbNombrePruebas) --------------------
#
# The legacy carries (NombrePrueba, Especie, Observaciones). The catalog
# keeps all three; codigo = nombre, especie verbatim, observaciones
# preserves the legacy hint about what to do with each test.


CATALOGOS_PRUEBAS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS catalogos_pruebas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    especie TEXT NOT NULL,
    observaciones TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT catalogos_pruebas_natural_key UNIQUE (codigo, especie)
)
"""

CATALOGOS_PRUEBAS_SEED_SQL = """
INSERT INTO catalogos_pruebas (codigo, nombre, especie, observaciones, orden)
VALUES
    ('Básico', 'Básico', 'ambos', 'analítica', 1),
    ('Desparasitación Externa', 'Desparasitación Externa', 'ambos', 'Pon producto', 2),
    ('Desparasitación Interna', 'Desparasitación Interna', 'ambos', 'Pon producto', 3),
    ('EHR', 'EHR', 'canina', 'analítica', 4),
    ('Esterilización', 'Esterilización', 'ambos', 'Pon Clínica', 5),
    ('Heptavalente', 'Heptavalente', 'canina', 'Vacuna', 6),
    ('IFI', 'IFI', 'felina', 'analítica', 7),
    ('LEUC', 'LEUC', 'felina', 'analítica', 8),
    ('Leucemia', 'Leucemia', 'felina', 'Vacuna', 9),
    ('LH', 'LH', 'canina', 'analítica', 10),
    ('Puppy', 'Puppy', 'canina', 'Vacuna', 11),
    ('Rabia', 'Rabia', 'ambos', 'Vacuna', 12),
    ('Trivalente', 'Trivalente', 'felina', 'Vacuna', 13)
ON CONFLICT (codigo, especie) DO NOTHING
"""

LIST_CATALOGOS_PRUEBAS_SQL = """
SELECT id, codigo, nombre, especie, observaciones, activo, orden
FROM catalogos_pruebas
WHERE activo = true
ORDER BY orden NULLS LAST, codigo
"""


# --- catalogos_periodicidad (12 rows from TbPruebasPeridicidad) ----------
#
# The legacy uses the column name ``PeridicidadEnMeses`` (the typo
# ``Peridicidad`` is preserved in the legacy). In the catalog we rename
# it to ``periodicidad_meses`` for clarity; ``Esterilizacion`` is
# conspicuously absent because the legacy has no periodicity row for
# it (the operation is one-shot, not periodic).
#
# All 12 rows report 12 months in the legacy as of 2026-07-03.


CATALOGOS_PERIODICIDAD_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS catalogos_periodicidad (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    periodicidad_meses INTEGER NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

CATALOGOS_PERIODICIDAD_SEED_SQL = """
INSERT INTO catalogos_periodicidad (codigo, nombre, periodicidad_meses, orden)
VALUES
    ('Básico', 'Básico', 12, 1),
    ('Desparasitación Externa', 'Desparasitación Externa', 12, 2),
    ('Desparasitación Interna', 'Desparasitación Interna', 12, 3),
    ('EHR', 'EHR', 12, 4),
    ('Heptavalente', 'Heptavalente', 12, 5),
    ('IFI', 'IFI', 12, 6),
    ('LEUC', 'LEUC', 12, 7),
    ('Leucemia', 'Leucemia', 12, 8),
    ('LH', 'LH', 12, 9),
    ('Puppy', 'Puppy', 12, 10),
    ('Rabia', 'Rabia', 12, 11),
    ('Trivalente', 'Trivalente', 12, 12)
ON CONFLICT (codigo) DO NOTHING
"""

LIST_CATALOGOS_PERIODICIDAD_SQL = """
SELECT id, codigo, nombre, periodicidad_meses, activo, orden
FROM catalogos_periodicidad
WHERE activo = true
ORDER BY orden NULLS LAST, codigo
"""


# --- catalogos_tipos_contrato (8 rows from TbPlantillas) ------------------
#
# These are the 8 contract-template types required by Fase 7
# (``docs/roadmap.md`` §3). The legacy carries each Plantilla's
# initial-letter codes (``InicialDocumento``), the table+column where
# the per-record contract number lives (``NombreTabla`` /
# ``NombreCampo``), and the description text. The catalog preserves
# all four so the future template engine can pick the right prefix and
# write to the right column without joining the legacy again.


CATALOGOS_TIPOS_CONTRATO_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS catalogos_tipos_contrato (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    iniciales TEXT,
    descripcion TEXT,
    tabla_legacy TEXT,
    campo_legacy TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

CATALOGOS_TIPOS_CONTRATO_SEED_SQL = """
INSERT INTO catalogos_tipos_contrato (codigo, nombre, iniciales, descripcion, tabla_legacy, campo_legacy, orden)
VALUES
    ('Acogida', 'Contrato de Acogida', 'AC;AT', 'Temporal;Condicionada', 'TbAcogidaAnimal', 'NCONTRATOACOGIDA', 1),
    ('Adopción', 'Contrato de Adopción', 'PA;AD', 'Preadopción,Adopción', 'TbAdopcion', 'Ncontrato', 2),
    ('Cesión', 'Cesión por Propietario', 'CP', 'Cesión entregada por el propietario', 'TbCesionPorPropietario', 'NCONTRATOCESION', 3),
    ('Entrada', 'Contrato de Entrada', 'ENT', 'Contrato de entrada en protectora', 'TbEntradas', 'NCONTRATOENTRADA', 4),
    ('Entregado a Propietario', 'Entrega a Propietario', 'ADE', 'Documento de entrega al propietario original', NULL, NULL, 5),
    ('Ficha de Seguimiento', 'Ficha de Seguimiento', 'SEG', 'Ficha de seguimiento post-adopción', NULL, NULL, 6),
    ('Ficha Sanitaria Gatos', 'Historial Sanitario de Gatos', 'FSG', 'Historial sanitario específico de gatos', NULL, NULL, 7),
    ('Ficha Sanitaria Perros', 'Historial Sanitario de Perros', 'FSP', 'Historial sanitario específico de perros', NULL, NULL, 8)
ON CONFLICT (codigo) DO NOTHING
"""

LIST_CATALOGOS_TIPOS_CONTRATO_SQL = """
SELECT id, codigo, nombre, iniciales, descripcion, tabla_legacy, campo_legacy, activo, orden
FROM catalogos_tipos_contrato
WHERE activo = true
ORDER BY orden NULLS LAST, codigo
"""


# --- Runner (DDL + seed, atomic per-catalog) ------------------------------


def ensure_catalogs(client: InsForgeClient) -> None:
    """Create all 5 catalog tables and seed them from the Access legacy.

    Each catalog runs CREATE-then-INSERT in order. ``CREATE TABLE IF
    NOT EXISTS`` plus ``INSERT ... ON CONFLICT (...) DO NOTHING`` make
    this idempotent across cold starts and partial deploys — a second
    invocation produces no observable state change.

    The DDL pairs are emitted in the order ``origenes``, ``motivos``,
    ``pruebas``, ``periodicidad``, ``tipos_contrato``. None of these
    tables have foreign-key dependencies on each other or on the
    domain tables (``animales``, ``voluntarios``, ...) so order is
    arbitrary; the chosen order matches the order they are listed in
    ``docs/discovery/feature-XX-catalogs.md`` and the issue body.

    Args:
        client: An ``InsForgeClient`` whose ``execute_sql`` POSTs to
            the InsForge ``/api/database/advance/rawsql`` endpoint.
    """
    pairs = (
        (CATALOGOS_ORIGENES_CREATE_SQL, CATALOGOS_ORIGENES_SEED_SQL),
        (CATALOGOS_MOTIVOS_CREATE_SQL, CATALOGOS_MOTIVOS_SEED_SQL),
        (CATALOGOS_PRUEBAS_CREATE_SQL, CATALOGOS_PRUEBAS_SEED_SQL),
        (CATALOGOS_PERIODICIDAD_CREATE_SQL, CATALOGOS_PERIODICIDAD_SEED_SQL),
        (CATALOGOS_TIPOS_CONTRATO_CREATE_SQL, CATALOGOS_TIPOS_CONTRATO_SEED_SQL),
    )
    statements = tuple(SqlStatement(query) for pair in pairs for query in pair)
    run_idempotent_sql(client, statements, step_name="catalogs")


# --- Read helpers --------------------------------------------------------
#
# Each ``list_catalogos_<name>`` is a thin wrapper over
# ``client.execute_sql`` with the corresponding ``LIST_*_SQL``
# constant. The wrappers return the raw rows as ``dict`` from the
# InsForge client; routes / templates can project to UI form on top.
# No row transformation is needed because ``execute_sql`` already
# returns ``list[dict[str, Any]]``.


def list_catalogos_origenes(client: InsForgeClient) -> list[dict[str, Any]]:
    """Return all active origenes ordered by their ``orden`` field."""
    return client.execute_sql(LIST_CATALOGOS_ORIGENES_SQL)


def list_catalogos_motivos(client: InsForgeClient) -> list[dict[str, Any]]:
    """Return all active motivos grouped by especie."""
    return client.execute_sql(LIST_CATALOGOS_MOTIVOS_SQL)


def list_catalogos_pruebas(client: InsForgeClient) -> list[dict[str, Any]]:
    """Return all active pruebas ordered by ``orden`` then ``codigo``."""
    return client.execute_sql(LIST_CATALOGOS_PRUEBAS_SQL)


def list_catalogos_periodicidad(
    client: InsForgeClient,
) -> list[dict[str, Any]]:
    """Return all active periodicidades ordered by ``orden`` then ``codigo``."""
    return client.execute_sql(LIST_CATALOGOS_PERIODICIDAD_SQL)


def list_catalogos_tipos_contrato(
    client: InsForgeClient,
) -> list[dict[str, Any]]:
    """Return all active contract-template types for Fase 7."""
    return client.execute_sql(LIST_CATALOGOS_TIPOS_CONTRATO_SQL)


__all__ = [
    "CATALOGOS_ORIGENES_CREATE_SQL",
    "CATALOGOS_ORIGENES_SEED_SQL",
    "CATALOGOS_MOTIVOS_CREATE_SQL",
    "CATALOGOS_MOTIVOS_SEED_SQL",
    "CATALOGOS_PRUEBAS_CREATE_SQL",
    "CATALOGOS_PRUEBAS_SEED_SQL",
    "CATALOGOS_PERIODICIDAD_CREATE_SQL",
    "CATALOGOS_PERIODICIDAD_SEED_SQL",
    "CATALOGOS_TIPOS_CONTRATO_CREATE_SQL",
    "CATALOGOS_TIPOS_CONTRATO_SEED_SQL",
    "LIST_CATALOGOS_ORIGENES_SQL",
    "LIST_CATALOGOS_MOTIVOS_SQL",
    "LIST_CATALOGOS_PRUEBAS_SQL",
    "LIST_CATALOGOS_PERIODICIDAD_SQL",
    "LIST_CATALOGOS_TIPOS_CONTRATO_SQL",
    "ensure_catalogs",
    "list_catalogos_origenes",
    "list_catalogos_motivos",
    "list_catalogos_pruebas",
    "list_catalogos_periodicidad",
    "list_catalogos_tipos_contrato",
]
