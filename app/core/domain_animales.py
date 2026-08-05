"""Domain: animales — SQL schema and Pydantic models for the animals table.

Bounded context: animales (issue #29, legacy TbFichaAnimal).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class Animal(BaseModel):
    """Pydantic model for the animales table (issue #29).

    Mirrors TbFichaAnimal legacy schema. System fields (id, fecha_alta,
    updated_at, activo) are included; legacy columns map 1:1 to the
    SQL column names.
    """

    id: UUID | None = None
    nchip: str
    traenchip: str | None = None
    fimplantacionchip: date | None = None
    nombreanimal: str
    especie: str = Field(..., pattern=r"^(CANINA|FELINA)$")
    sexo: str = Field(..., pattern=r"^[MH]$")
    raza: str | None = None
    color: str | None = None
    pelo: str | None = None
    tamano: str | None = None
    caracter: str | None = None
    fnacimiento: date
    fdefuncion: date | None = None
    terapia: str | None = None
    observaciones: str | None = None
    nombrefoto: str | None = None
    cartilla: str | None = None
    eutanasia: str | None = None
    razappp: str | None = None
    mestizo: str | None = None
    eutanasia_otras_causas: str | None = None
    eutanasia_enfermedad: str | None = None
    ultimo_estado_antes_de_fallecido: str | None = None
    comunicacionariac: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


# SQL constant (moved from app/core/domain.py)
ANIMALS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nchip TEXT UNIQUE NOT NULL,
    traenchip TEXT,
    fimplantacionchip DATE,
    nombreanimal TEXT NOT NULL,
    especie TEXT NOT NULL CHECK (especie IN ('CANINA', 'FELINA')),
    sexo TEXT NOT NULL CHECK (sexo IN ('M', 'H')),
    raza TEXT,
    color TEXT,
    pelo TEXT,
    tamano TEXT,
    caracter TEXT,
    fnacimiento DATE NOT NULL,
    fdefuncion DATE,
    terapia TEXT,
    observaciones TEXT,
    nombrefoto TEXT,
    cartilla TEXT,
    eutanasia TEXT,
    razappp TEXT,
    mestizo TEXT,
    eutanasia_otras_causas TEXT,
    eutanasia_enfermedad TEXT,
    ultimo_estado_antes_de_fallecido TEXT,
    comunicacionariac TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

__all__ = ["ANIMALS_CREATE_TABLE_SQL"]
