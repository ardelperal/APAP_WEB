"""Domain: lifecycle — SQL schema, Pydantic models, indices and the
append-only trigger for the lifecycle-event log.

Bounded context: lifecycle (LIFECYCLE-02, issue #32; PR 1 of
web-only-feature-preservation).

Append-only contract (issue #32 acceptance: "Event log es append-only
(sin UPDATE/DELETE en BD; tests verifican esto)"):

- ``animal_lifecycle_events_append_only`` is a ``BEFORE UPDATE OR
  DELETE`` trigger that raises an exception, so a buggy retry /
  migration tool cannot silently mutate or delete events. The
  enforcement is structural: a future ALTER that drops the trigger
  has to come with the same justification it took to add it.
- The trigger installation is idempotent (``DROP TRIGGER IF EXISTS``
  + ``CREATE TRIGGER``) so the bootstrap stays replay-safe across
  cold starts (lifespan runs every process boot).
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

# Index 1/2 of the 4 indices on animal_lifecycle_events (issue #32
# acceptance: "14 columnas, 4 indices"). The PK on ``id`` and the
# UNIQUE constraint on ``(animal_id, event_type, event_timestamp)``
# auto-create 2 indices; we add 2 more for the read patterns the
# timeline page + the audit graph rely on.
#
# - ``idx_animal_lifecycle_events_animal_timestamp`` accelerates the
#   canonical timeline read: ``SELECT … WHERE animal_id = $1 ORDER BY
#   event_timestamp DESC``.
# - ``idx_animal_lifecycle_events_caused_by`` accelerates the
#   causal-chain walk: ``SELECT … WHERE caused_by_event_id = $1``.
ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_animal_lifecycle_events_animal_timestamp
ON animal_lifecycle_events (animal_id, event_timestamp DESC)
"""

ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_animal_lifecycle_events_caused_by
ON animal_lifecycle_events (caused_by_event_id)
"""

# Append-only trigger: ``BEFORE UPDATE OR DELETE`` on the event log
# raises an exception so a buggy retry / migration tool cannot mutate
# or delete events. Idempotent installation via ``DROP TRIGGER IF
# EXISTS`` so the bootstrap is replay-safe across cold starts.
ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS animal_lifecycle_events_append_only ON animal_lifecycle_events
"""

ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER animal_lifecycle_events_append_only
BEFORE UPDATE OR DELETE ON animal_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION raise_append_only_violation()
"""

# The trigger function is created once and shared by the trigger. It
# raises an exception so the UPDATE/DELETE aborts before touching any
# row. The function name is hardcoded in the trigger SQL above, so any
# change here must be mirrored in the trigger.
ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION raise_append_only_violation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'animal_lifecycle_events is append-only (issue #32 D-23 / LIFECYCLE-02): '
        'UPDATE and DELETE are rejected at the SQL level. '
        'Use a follow-up event with caused_by_event_id pointing at the prior '
        'event to record a correction, or open a maintenance ticket to amend '
        'historical events through the dedicated admin path.';
END;
$$ LANGUAGE plpgsql
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

# Index 2/2 of the 2 indices on animal_current_state (issue #32
# acceptance: "cache materializado animal_current_state (11 columnas,
# 2 indices)"). The PK on ``animal_id`` is auto-index #1; the second
# index accelerates "all animals currently in state X" dashboard
# reads.
ANIMAL_CURRENT_STATE_STATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_animal_current_state_state
ON animal_current_state (current_state)
"""


__all__ = [
    "AnimalLifecycleEvent",
    "AnimalCurrentState",
    "ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL",
    "ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL",
    "ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL",
    "ANIMAL_CURRENT_STATE_STATE_INDEX_SQL",
]
