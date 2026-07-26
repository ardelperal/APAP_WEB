"""Domain: voluntarios — SQL schema and Pydantic models for volunteers and roles.

Bounded context: voluntarios.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class Voluntario(BaseModel):
    """Pydantic model for the voluntarios table."""

    id: UUID | None = None
    Voluntario: str
    Tel1: str | None = None
    Tel2: str | None = None
    Email: str | None = None
    DNI: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
    activo: bool = True

    model_config = {"from_attributes": True}


VOLUNTARIOS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS voluntarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    Voluntario TEXT NOT NULL,
    Tel1 TEXT,
    Tel2 TEXT,
    Email TEXT UNIQUE,
    DNI TEXT UNIQUE,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

ROLES_VOLUNTARIO_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS roles_voluntario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voluntario_id UUID NOT NULL REFERENCES voluntarios(id),
    tipo_rol TEXT NOT NULL CHECK (tipo_rol IN ('intake', 'seguimiento', 'acogida', 'salud')),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (voluntario_id, tipo_rol)
)
"""

__all__ = ["VOLUNTARIOS_CREATE_TABLE_SQL", "ROLES_VOLUNTARIO_CREATE_TABLE_SQL"]
