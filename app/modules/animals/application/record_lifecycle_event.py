"""Use case: append one event to the animal lifecycle log.

Slice #420-7 sixth surface (joins get_animal_by_nchip #587,
list_animals #596, create_animal #597, update_animal #603 and
delete_animal #604). The single application-layer entry point
for hexagonal lifecycle-event recording. Delegates to
:class:`~app.modules.animals.ports.AnimalsPort` so the application
code stays transport-agnostic (AGENTS.md §31) — no FastAPI, no
InsForge, no Jinja in this file.

The use case enforces the two pre-flight invariants the legacy
``lifecycle_events.record_event`` did:

- ``animal_id`` is mandatory and must be non-blank.
- ``created_by`` is mandatory and must be non-blank.

The two enum fields (``LifecycleEventType``) and ``event_timestamp``
go through unchanged — invalid enum values raise ``ValueError`` in
the StrEnum constructor and the application lets the
``InvalidTimestampError`` propagate so the route handler
translates it into a 422.
"""
from __future__ import annotations

from datetime import datetime

from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)
from app.modules.animals.ports.animals_port import AnimalsPort


class LifecycleEventValidationError(ValueError):
    """Raised when ``animal_id`` or ``created_by`` fail the domain rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it.
    """


def _require_non_blank(value: str | None, field_name: str) -> str:
    if value is None:
        raise LifecycleEventValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"{field_name} es obligatorio"
        )
    stripped = value.strip()
    if not stripped:
        raise LifecycleEventValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"{field_name} es obligatorio y no puede estar vacio"
        )
    return stripped


def record_lifecycle_event(
    animals_port: AnimalsPort,
    *,
    animal_id: str,
    event_type: LifecycleEventType,
    event_timestamp: str | datetime,
    created_by: str,
    caused_by_event_id: str | None = None,
    source_entity_type: str | None = None,
    source_entity_id: str | None = None,
    legacy_source_table: str | None = None,
    legacy_source_id: int | None = None,
    metadata: dict | None = None,
) -> AnimalLifecycleEvent:
    """Append one event to ``animal_lifecycle_events`` and return the row.

    Idempotent: the adapter uses ``ON CONFLICT (animal_id, event_type,
    event_timestamp) DO NOTHING`` so a retry collapses to the existing
    row. The adapter returns the existing event in that case — the
    caller does not have to re-query.
    """
    clean_animal_id = _require_non_blank(animal_id, "animal_id")
    clean_created_by = _require_non_blank(created_by, "created_by")

    return animals_port.record_lifecycle_event(
        animal_id=clean_animal_id,
        event_type=event_type,
        event_timestamp=event_timestamp,
        created_by=clean_created_by,
        caused_by_event_id=caused_by_event_id,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        legacy_source_table=legacy_source_table,
        legacy_source_id=legacy_source_id,
        metadata=metadata,
    )


__all__ = ["record_lifecycle_event", "LifecycleEventValidationError"]
