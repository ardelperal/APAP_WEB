"""Domain: contracts — SQL schema and Pydantic models for contract metadata.

Bounded context: contracts (Fase 7, legacy TbContratosAnexos).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class Contrato(BaseModel):
    """Pydantic model for the contratos table (polymorphic, Fase 7)."""

    id: UUID | None = None
    tipo_contrato_id: UUID
    numero_contrato: str
    fecha: date
    entrada_id: UUID | None = None
    acogida_id: UUID | None = None
    adopcion_id: UUID | None = None
    cesion_id: UUID | None = None
    nombre_archivo: str | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


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

__all__ = ["CONTRATOS_CREATE_TABLE_SQL"]
