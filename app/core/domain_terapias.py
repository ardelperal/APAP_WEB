"""Domain: salud — SQL schema for terapias and recomendaciones (HEALTH-04, issue #53).

Bounded context: salud (HEALTH-04, issue #53).
"""

from __future__ import annotations

TERAPIAS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS terapias (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    fecha DATE NOT NULL,
    voluntario_id UUID NOT NULL REFERENCES voluntarios(id),
    descripcion TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

RECOMENDACIONES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS recomendaciones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    terapia_id UUID NOT NULL REFERENCES terapias(id) ON DELETE CASCADE,
    fecha DATE NOT NULL,
    texto TEXT NOT NULL,
    completada BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
"""

__all__ = [
    "TERAPIAS_CREATE_TABLE_SQL",
    "RECOMENDACIONES_CREATE_TABLE_SQL",
]
