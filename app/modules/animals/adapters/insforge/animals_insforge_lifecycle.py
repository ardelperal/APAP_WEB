"""Lifecycle-event persistence for the animals InsForge adapter."""
from __future__ import annotations

from datetime import datetime

from app.core.data_access import SqlExecutor
from app.modules.animals.adapters.insforge.animals_insforge_mappers import (
    _row_to_lifecycle_event,
)
from app.modules.animals.adapters.insforge.animals_insforge_queries import (
    list_lifecycle_events_sql,
    record_lifecycle_event_sql,
)
from app.modules.animals.domain.lifecycle_event import (
    AnimalLifecycleEvent,
    LifecycleEventType,
)


def record_lifecycle_event(  # noqa: PLR0913  # lineage fields mirror the lifecycle port contract
    client: SqlExecutor,
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
    """Persist one event and map the returned transport row."""
    timestamp = (
        event_timestamp.isoformat()
        if isinstance(event_timestamp, datetime)
        else event_timestamp
    )
    sql, params = record_lifecycle_event_sql(
        animal_id=animal_id,
        event_type=event_type.value,
        event_timestamp=timestamp,
        created_by=created_by,
        caused_by_event_id=caused_by_event_id,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        legacy_source_table=legacy_source_table,
        legacy_source_id=legacy_source_id,
        metadata=metadata,
    )
    rows = client.execute_sql(sql, params)
    if not rows:
        raise RuntimeError(  # noqa: TRY003 — operator-facing transport-shape diagnostic
            "INSERT INTO animal_lifecycle_events ON CONFLICT DO NOTHING "
            "RETURNING produced no rows; expected exactly one row."
        )
    return _row_to_lifecycle_event(rows[0])


def list_lifecycle_events(
    client: SqlExecutor,
    animal_id: str,
    *,
    limit: int,
    offset: int,
    event_types: list[LifecycleEventType] | None,
) -> list[AnimalLifecycleEvent]:
    """Return mapped lifecycle events in chronological order."""
    sql, params = list_lifecycle_events_sql(
        animal_id=animal_id,
        limit=limit,
        offset=offset,
        event_types=[event_type.value for event_type in event_types] if event_types else None,
    )
    rows = client.execute_sql(sql, params)
    return [_row_to_lifecycle_event(row) for row in rows]


__all__ = ["list_lifecycle_events", "record_lifecycle_event"]
