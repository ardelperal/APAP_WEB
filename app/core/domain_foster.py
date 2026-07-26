"""Domain: foster — Pydantic model and SQL for acogidas.

Part of bounded context: foster (FOSTER-01..04, issues #43..46).
ACOGIDAS_ADD_CASA_FK_SQL is emitted after both ACOGIDAS and CASAS_ACOGIDA
are created, so it is kept in this module alongside ACOGIDAS.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class Acogida(BaseModel):
    """Pydantic model for the acogidas table (LIFECYCLE-03)."""

    id: UUID | None = None
    animal_id: UUID
    voluntario_acogida_id: UUID | None = None
    voluntario_seguimiento1_id: UUID | None = None
    voluntario_seguimiento2_id: UUID | None = None
    voluntario_sanitario_id: UUID | None = None
    fecha_inicio: date
    fecha_final: date | None = None
    entrada_origen_id: UUID | None = None
    direccion: str | None = None
    telefono: str | None = None
    observaciones: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True
    casa_acogida_id: UUID | None = None

    model_config = {"from_attributes": True}


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

ACOGIDAS_ADD_CASA_FK_SQL = """
ALTER TABLE acogidas
ADD COLUMN IF NOT EXISTS casa_acogida_id UUID REFERENCES casas_acogida(id)
"""

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

FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL = """
ALTER TABLE foster_capacity_overrides
ADD COLUMN IF NOT EXISTS estancia_id UUID NULL REFERENCES acogidas(id)
"""

__all__ = [
    "Acogida",
    "ACOGIDAS_CREATE_TABLE_SQL",
    "ACOGIDAS_ADD_CASA_FK_SQL",
    "FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL",
    "FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL",
]
