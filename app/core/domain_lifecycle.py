"""Domain: lifecycle — SQL schema and Pydantic models for animal lifecycle events.

Bounded context: lifecycle (LIFECYCLE-SCHEMA-02, web-only-feature-preservation PR 1).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AnimalLifecycleEvent(BaseModel):
    """Pydantic model for the animal_lifecycle_events table."""

    id: UUID | None = None
    animal_id: UUID
    event_type: str
    event_timestamp: datetime
    caused_by_event_id: UUID | None = None
    source_entity_type: str | None = None
    source_entity_id: UUID | None = None
    legacy_source_table: str | None = None
    legacy_source_id: int | None = None
    metadata: dict | None = None
    created_by: UUID
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AnimalCurrentState(BaseModel):
    """Pydantic model for the animal_current_state table."""

    animal_id: UUID
    current_state: str
    active_event_id: UUID | None = None
    active_intake_id: UUID | None = None
    active_foster_id: UUID | None = None
    active_adoption_id: UUID | None = None
    pre_death_state: str | None = None
    state_changed_at: datetime | None = None
    legacy_situacion: str | None = None
    legacy_ultimo_estado: str | None = None
    reconciliation_status: str = "pending"

    model_config = {"from_attributes": True}


ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animal_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    animal_id UUID NOT NULL REFERENCES animales(id),
    event_type VARCHAR(50) NOT NULL CHECK (event_type IN (
        'INTAKE_STARTED', 'INTAKE_COMPLETED',
        'FOSTER_STARTED', 'FOSTER_RETURNED', 'FOSTER_CLOSED_BY_ADOPTION',
        'ADOPTION_STARTED', 'ADOPTION_RETURNED',
        'OWNER_RETURNED', 'DEATH_RECORDED',
        'STATE_CORRECTION',
        'CHIP_CHANGED', 'INTAKE_REOPENED', 'FOSTER_REOPENED', 'ADOPTION_REOPENED'
    )),
    event_timestamp TIMESTAMPTZ NOT NULL,
    caused_by_event_id UUID REFERENCES animal_lifecycle_events(id),
    source_entity_type VARCHAR(30),
    source_entity_id UUID,
    legacy_source_table VARCHAR(50),
    legacy_source_id INTEGER,
    metadata JSONB,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT animal_lifecycle_events_natural_key UNIQUE (animal_id, event_type, event_timestamp)
)
"""

ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animal_current_state (
    animal_id UUID PRIMARY KEY REFERENCES animales(id),
    current_state VARCHAR(50) NOT NULL CHECK (current_state IN (
        'Pendiente de Entrada',
        'Pendiente de Nueva Situación',
        'Albergue', 'Acogida', 'Adoptado',
        'Entregado',
        'Fallecido (Albergue)', 'Fallecido (Acogida)',
        'Fallecido (Adoptado)', 'Fallecido (Entregado)',
        'Fallecido (Desconocido)',
        'Incoherente'
    )),
    active_event_id UUID REFERENCES animal_lifecycle_events(id),
    active_intake_id UUID,
    active_foster_id UUID,
    active_adoption_id UUID,
    pre_death_state VARCHAR(50),
    state_changed_at TIMESTAMPTZ NOT NULL,
    legacy_situacion VARCHAR(100),
    legacy_ultimo_estado VARCHAR(50),
    reconciliation_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (reconciliation_status IN ('matched', 'divergent', 'migrated', 'pending'))
)
"""

__all__ = ["ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL", "ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL"]
