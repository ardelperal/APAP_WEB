"""catalogos_* CREATE TABLE DDL — single source of truth for the schema layout.

The five ``CATALOGOS_*_CREATE_TABLE_SQL`` constants used by both
``app.core.schema_provisioning`` (production provisioning: verify gate,
ad-hoc scripts, Coolify local backend) and ``tests/integration/conftest.py``
(ephemeral test schema) live here so production code never imports the
test tree (issue #921, finding A-09).

Schemas verified 2026-08-01 against the LocalBackend project's underlying
Postgres via ``local_backend.get-table-schema`` MCP. The statements cover
the seed tables migrated from the legacy Access database (issue #329
follow-up); the FK from ``contratos`` to ``catalogos_tipos_contrato``
requires them to exist before the domain tables.

This module is deliberately a sibling of the pure dataclass modules in
this package: importing ``app.core.catalogos`` still yields only the
value objects, and only consumers that need the DDL import this module.

Do not edit the SQL here without verifying it against the live
LocalBackend schema — these statements define the deployed table layout.
"""

from __future__ import annotations

CATALOGOS_MOTIVOS_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_motivos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    especie TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_motivos_natural_key
    ON catalogos_motivos (codigo, especie);
"""

CATALOGOS_ORIGENES_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_origenes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_origenes_codigo_key
    ON catalogos_origenes (codigo);
"""

CATALOGOS_PERIODICIDAD_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_periodicidad (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    periodicidad_meses INTEGER NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_periodicidad_codigo_key
    ON catalogos_periodicidad (codigo);
"""

CATALOGOS_PRUEBAS_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_pruebas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    especie TEXT NOT NULL,
    observaciones TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_pruebas_natural_key
    ON catalogos_pruebas (codigo, especie);
"""

CATALOGOS_TIPOS_CONTRATO_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_tipos_contrato (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    iniciales TEXT,
    descripcion TEXT,
    tabla_legacy TEXT,
    campo_legacy TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_tipos_contrato_codigo_key
    ON catalogos_tipos_contrato (codigo);
"""

__all__ = [
    "CATALOGOS_MOTIVOS_CREATE_TABLE_SQL",
    "CATALOGOS_ORIGENES_CREATE_TABLE_SQL",
    "CATALOGOS_PERIODICIDAD_CREATE_TABLE_SQL",
    "CATALOGOS_PRUEBAS_CREATE_TABLE_SQL",
    "CATALOGOS_TIPOS_CONTRATO_CREATE_TABLE_SQL",
]
