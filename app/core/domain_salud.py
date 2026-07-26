"""Domain: salud — SQL schema and Pydantic models for veterinary health records.

Bounded context: salud (HEALTH-01, issue #50).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class ActuacionSanitaria(BaseModel):
    """Pydantic model for the actuacion_sanitaria table (HEALTH-01, issue #50)."""

    id: UUID | None = None
    animal_id: UUID
    fecha: date
    tipo_actuacion_id: UUID | None = None
    veterinario: str | None = None
    observaciones: str | None = None
    voluntario_id: UUID | None = None
    material_utilizado: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


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

__all__ = ["ACTUACION_SANITARIA_CREATE_TABLE_SQL"]
