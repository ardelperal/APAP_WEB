"""Domain: adopciones — SQL schema and Pydantic models for adoptions.

Bounded context: adopciones (LIFECYCLE-03, legacy TbAdopcion).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class Adopcion(BaseModel):
    """Pydantic model for the adopciones table (LIFECYCLE-03)."""

    id: UUID | None = None
    animal_id: UUID
    voluntario_seguimiento_id: UUID | None = None
    fecha_adopcion: date
    fecha_devolucion: date | None = None
    donativo_preadopcion: float | None = None
    donativo_adopcion: float | None = None
    nombre_adoptante: str
    dni_adoptante: str | None = None
    telefono_adoptante: str | None = None
    email_adoptante: str | None = None
    entrada_origen_id: UUID | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


ADOPCIONES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS adopciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    voluntario_seguimiento_id UUID REFERENCES voluntarios(id),
    responsable_adopcion_id UUID REFERENCES voluntarios(id),
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
    tipo_adopcion TEXT NOT NULL DEFAULT 'regular' CHECK (tipo_adopcion IN ('regular', 'preadopcion', 'judicial')),
    seguimiento_estado TEXT NOT NULL DEFAULT 'pendiente',
    seguimiento_documento_entregado_at TIMESTAMPTZ,
    seguimiento_documento_url TEXT,
    seguimiento_completado_at TIMESTAMPTZ,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT adopciones_natural_key UNIQUE (animal_id, fecha_adopcion)
)
"""

__all__ = ["ADOPCIONES_CREATE_TABLE_SQL"]
