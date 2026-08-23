"""Domain entities for the animal lifecycle event log (AGENTS.md §31).

``AnimalLifecycleEvent`` is the hexagonal read/write projection of
the legacy ``animal_lifecycle_events`` table. The slice is
append-only by SQL trigger (issue #32, D-23), so the dataclass
mirrors the columns the writer and the future reader will both
need: ``event_type`` (one of the 14 ``LifecycleEventType``
members), ``event_timestamp`` (ISO 8601 string), and the lineage
fields (``caused_by_event_id``) plus the audit trail
(``operador_user_id``, ``source_entity_type`` /
``source_entity_id``, ``legacy_source_table`` / ``legacy_source_id``).

The 14 ``LifecycleEventType`` members are pinned per the legacy
``CHECK (event_type IN (...))`` constraint in
``ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL``. Adding a new event
type means BOTH adding a member here AND extending the CHECK
constraint — the ratchet on ``core_event_types_set_matches_strenum_members``
in the test suite enforces this.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LifecycleEventType(StrEnum):
    """The 14 pinned lifecycle event types (issue #32 acceptance).

    See :mod:`app.modules.animals.lifecycle_events` for the legacy
    definitions and the per-type semantics.
    """

    INTAKE_STARTED = "INTAKE_STARTED"
    INTAKE_COMPLETED = "INTAKE_COMPLETED"
    FOSTER_STARTED = "FOSTER_STARTED"
    FOSTER_RETURNED = "FOSTER_RETURNED"
    FOSTER_CLOSED_BY_ADOPTION = "FOSTER_CLOSED_BY_ADOPTION"
    ADOPTION_STARTED = "ADOPTION_STARTED"
    ADOPTION_RETURNED = "ADOPTION_RETURNED"
    OWNER_RETURNED = "OWNER_RETURNED"
    DEATH_RECORDED = "DEATH_RECORDED"
    STATE_CORRECTION = "STATE_CORRECTION"
    CHIP_CHANGED = "CHIP_CHANGED"
    INTAKE_REOPENED = "INTAKE_REOPENED"
    FOSTER_REOPENED = "FOSTER_REOPENED"
    ADOPTION_REOPENED = "ADOPTION_REOPENED"


@dataclass(frozen=True, slots=True)
class AnimalLifecycleEvent:
    """A row of the ``animal_lifecycle_events`` table as the hexagonal
    surface needs it.

    ``id`` and ``created_at`` are system columns populated by the
    INSERT ... RETURNING path. The other fields mirror the legacy
    table; ``metadata`` is JSON-typed on the wire and round-trips as
    ``dict`` here.
    """

    id: str
    animal_id: str
    event_type: LifecycleEventType
    event_timestamp: str
    created_by: str
    caused_by_event_id: str | None = None
    source_entity_type: str | None = None
    source_entity_id: str | None = None
    legacy_source_table: str | None = None
    legacy_source_id: int | None = None
    metadata: dict | None = None


__all__ = ["AnimalLifecycleEvent", "LifecycleEventType"]
