"""Domain: foster — Pydantic model and SQL for casas_acogida.

Part of bounded context: foster (FOSTER-01, issue #43).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class CasaAcogida(BaseModel):
    """Pydantic model for the casas_acogida table (FOSTER-01, issue #43)."""

    id: UUID | None = None
    nombre: str
    apellidos: str
    dni_acogedor: str | None = None
    calle: str
    numero: str | None = None
    piso: str | None = None
    letra: str | None = None
    localidad: str
    provincia: str
    cp: str | None = None
    telefono: str
    telefono2: str | None = None
    email: str | None = None
    vinculacion: str | None = None
    caracteristicas: str | None = None
    coche: str | None = None
    especie_preferente: str | None = None
    observaciones: str | None = None
    capacidad: int
    fecha_alta: str | None = None
    fecha_baja: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


CASAS_ACOGIDA_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS casas_acogida (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    apellidos TEXT NOT NULL,
    dni_acogedor TEXT,
    calle TEXT NOT NULL,
    numero TEXT,
    piso TEXT,
    letra TEXT,
    localidad TEXT,
    provincia TEXT,
    cp TEXT,
    telefono TEXT NOT NULL,
    telefono2 TEXT,
    email TEXT,
    vinculacion TEXT,
    caracteristicas TEXT,
    coche TEXT NOT NULL CHECK (coche IN ('Sí', 'No')),
    especie_preferente TEXT CHECK (
        especie_preferente IS NULL
        OR especie_preferente IN ('CANINA', 'FELINA')
    ),
    observaciones TEXT,
    capacidad INTEGER NOT NULL CHECK (capacidad > 0),
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    fecha_baja TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

__all__ = ["CasaAcogida", "CASAS_ACOGIDA_CREATE_TABLE_SQL"]
