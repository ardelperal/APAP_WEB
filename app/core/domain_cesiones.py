"""Domain: cesiones — SQL schema and Pydantic models for owner-surrender.

Bounded context: cesiones (issue #41, legacy TbCesionPorPropietario).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class CesionPropietario(BaseModel):
    """Pydantic model for the cesiones_propietario table (issue #41)."""

    id: UUID | None = None
    entrada_id: UUID
    numero_contrato: str
    nombre_representante: str
    cartilla_sanitaria: str | None = None
    certificado_veterinario: str | None = None
    autorizacion_recogida: str | None = None
    fecha_vacuna_rabia: date | None = None
    numero_colegiado: str | None = None
    numero_colaborador: str | None = None
    dni_representante: str | None = None
    calle_representante: str | None = None
    numero_calle_representante: str | None = None
    piso_representante: str | None = None
    letra_representante: str | None = None
    localidad_representante: str | None = None
    provincia_representante: str | None = None
    cp_representante: str | None = None
    telefono_representante: str | None = None
    email_representante: str | None = None
    hora_cesion: datetime | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}


CESIONES_PROPIETARIO_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cesiones_propietario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entrada_id UUID NOT NULL UNIQUE REFERENCES entradas(id),
    numero_contrato TEXT NOT NULL,
    nombre_representante TEXT NOT NULL,
    cartilla_sanitaria TEXT CHECK (
        cartilla_sanitaria IS NULL
        OR cartilla_sanitaria IN ('Sí', 'No')
    ),
    certificado_veterinario TEXT CHECK (
        certificado_veterinario IS NULL
        OR certificado_veterinario IN ('Sí', 'No')
    ),
    autorizacion_recogida TEXT CHECK (
        autorizacion_recogida IS NULL
        OR autorizacion_recogida IN ('Sí', 'No')
    ),
    fecha_vacuna_rabia DATE,
    numero_colegiado TEXT,
    numero_colaborador TEXT,
    dni_representante TEXT,
    calle_representante TEXT,
    numero_calle_representante TEXT,
    piso_representante TEXT,
    letra_representante TEXT,
    localidad_representante TEXT,
    provincia_representante TEXT,
    cp_representante TEXT,
    telefono_representante TEXT,
    email_representante TEXT,
    hora_cesion TIMESTAMP,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

__all__ = ["CESIONES_PROPIETARIO_CREATE_TABLE_SQL"]
