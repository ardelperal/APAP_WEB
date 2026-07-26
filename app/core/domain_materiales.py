"""Domain: materiales — SQL schema and Pydantic models for materials catalog.

Bounded context: materiales (FOSTER-04, issue #46).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class Material(BaseModel):
    """Pydantic model for the materiales table (FOSTER-04, issue #46)."""

    id: UUID | None = None
    material: str
    tamano: str
    color: str
    observaciones: str | None = None
    activo: bool = True
    fecha_alta: str | None = None
    updated_at: str | None = None
    fecha_baja: str | None = None

    model_config = {"from_attributes": True}


class EstanciaMaterial(BaseModel):
    """Pydantic model for the estancia_materiales junction (FOSTER-04)."""

    id: UUID | None = None
    estancia_id: UUID
    material_id: UUID
    cantidad: int = 1
    notas: str | None = None
    fecha_alta: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


MATERIALES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS materiales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material TEXT NOT NULL,
    tamano TEXT NOT NULL,
    color TEXT NOT NULL,
    observaciones TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    fecha_baja TIMESTAMP,
    UNIQUE (material, tamano, color)
)
"""

ESTANCIA_MATERIALES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS estancia_materiales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    estancia_id UUID NOT NULL REFERENCES acogidas(id),
    material_id UUID NOT NULL REFERENCES materiales(id),
    cantidad INTEGER NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    notas TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS estancia_materiales_active_unique
ON estancia_materiales (estancia_id, material_id)
WHERE activo = true
"""

__all__ = [
    "MATERIALES_CREATE_TABLE_SQL",
    "ESTANCIA_MATERIALES_CREATE_TABLE_SQL",
    "ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL",
]
