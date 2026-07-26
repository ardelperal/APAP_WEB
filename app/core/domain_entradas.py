"""Domain: entradas — SQL schema and Pydantic models for intake entries.

Bounded context: entradas (migration-compatible, INTAKE-02).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class Entrada(BaseModel):
    """Pydantic model for the entradas table (intake entries)."""

    id: UUID | None = None
    animal_id: UUID
    voluntario_entrada_id: UUID | None = None
    voluntario_salida_id: UUID | None = None
    fecha_entrada: date
    fecha_salida: date | None = None
    fecha_entrega_propietario: date | None = None
    origen: str | None = None
    motivo: str | None = None
    observaciones: str | None = None
    donativo_entregador: float | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


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

__all__ = ["ENTRADAS_CREATE_TABLE_SQL", "ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL"]
