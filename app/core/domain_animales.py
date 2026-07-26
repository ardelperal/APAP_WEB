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
    NCHIP: str
    TraeNChip: str | None = None
    FIMPLANTACIONCHIP: date | None = None
    NombreAnimal: str
    Especie: str = Field(..., pattern=r"^(CANINA|FELINA)$")
    Sexo: str = Field(..., pattern=r"^[MH]$")
    Raza: str | None = None
    Color: str | None = None
    Pelo: str | None = None
    Tamano: str | None = None
    Caracter: str | None = None
    FNacimiento: date
    FDefuncion: date | None = None
    Terapia: str | None = None
    Observaciones: str | None = None
    NombreFoto: str | None = None
    Cartilla: str | None = None
    Eutanasia: str | None = None
    RazaPPP: str | None = None
    Mestizo: str | None = None
    EutanasiaOtrasCausas: str | None = None
    EutanasiaEnfermedad: str | None = None
    UltimoEstadoAntesDeFallecido: str | None = None
    ComunicacionARIAC: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


# SQL constant (moved from app/core/domain.py)
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

__all__ = ["ANIMALS_CREATE_TABLE_SQL"]
