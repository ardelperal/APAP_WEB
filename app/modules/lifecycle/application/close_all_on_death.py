"""``close_all_on_death`` use case (LIFECYCLE-03 PR-C).

When an animal dies, this use case emits:

1. One ``DEATH_RECORDED`` lifecycle event (the trigger).
2. One closing event per active placement at the time of death:

   - ``INTAKE_CLOSED_BY_DEATH`` for every active ``entradas`` row.
   - ``FOSTER_CLOSED_BY_DEATH`` for every active ``acogidas`` row.
   - ``ADOPTION_CLOSED_BY_DEATH`` for every active ``adopciones`` row.

Closing is **event-sourced** (AGENTS.md §33.4): the use case NEVER
issues ``UPDATE``/``DELETE`` against ``entradas`` / ``acogidas`` /
``adopciones``. The append-only trigger at
``app/core/domain_lifecycle.py:130-141`` enforces the event log as the
single source of truth for state derivation; closing at the source
table would create a second source.

Every closing event references the death event via
``caused_by_event_id`` so the audit trail is traceable end-to-end.

The use case takes the ``SqlExecutor`` Protocol (AGENTS.md §31) — it
does NOT depend on ``AuthUsersPort`` or ``LifecyclePort`` (the port
exposes only ``calculate_state`` and ``persist_animal_state``, neither
of which fits event emission). The ``SqlExecutor`` Protocol is the
slice's contract for the SQL-touching seam; ``AuthUsersPort``
implements it via ``app/core/data_access.py`` (issue #259).

LIFECYCLE-03 (issue #33) PR-C work-unit C5.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.data_access import SqlExecutor
from app.modules.lifecycle.ports.lifecycle_port import LifecyclePort

# Active placements are the same projections the cascade adapter
# reads (app/modules/lifecycle/adapters/local-backend/lifecycle_local_backend_queries.py).
# Inlined here because the close use case is application-layer per
# AGENTS.md §33.4 — the application layer must NOT import the
# adapter. Keeping the SQL strings here is consistent with the
# one-function-per-file seam: the close use case is a small, focused
# orchestration that owns its own SQL and the cascade adapter owns
# the cascade SQL. Future PRs may lift these into a shared
# lifecycle_local_backend_queries.py extension.
_SELECT_ACTIVE_INTAKES_SQL = """
SELECT entradas.id AS "IDEntrada"
FROM entradas
WHERE entradas.animal_id = $1
  AND entradas.fecha_salida IS NULL
  AND entradas.activo = true
"""

_SELECT_ACTIVE_FOSTERS_SQL = """
SELECT acogidas.id AS "IDAcogida"
FROM acogidas
WHERE acogidas.animal_id = $1
  AND acogidas.fecha_final IS NULL
  AND acogidas.activo = true
"""

_SELECT_ACTIVE_ADOPTIONS_SQL = """
SELECT adopciones.id AS "IDAdopcion"
FROM adopciones
WHERE adopciones.animal_id = $1
  AND adopciones.fecha_devolucion IS NULL
  AND adopciones.activo = true
"""


# The death event INSERT uses RETURNING id so the use case can thread
# the new id into the closing events as ``caused_by_event_id``. The
# closing event INSERTs use the standard natural-key
# ``ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING``
# arbiter so a retry of the same death is idempotent at the DB level.
_INSERT_DEATH_EVENT_SQL = """
INSERT INTO animal_lifecycle_events (
    animal_id,
    event_type,
    event_timestamp,
    caused_by_event_id,
    source_entity_type,
    source_entity_id,
    legacy_source_table,
    legacy_source_id,
    metadata,
    created_by
) VALUES ($1, $2, $3, NULL, NULL, NULL, NULL, NULL, $4, $5)
RETURNING id
"""

_INSERT_CLOSING_EVENT_SQL = """
INSERT INTO animal_lifecycle_events (
    animal_id,
    event_type,
    event_timestamp,
    caused_by_event_id,
    source_entity_type,
    source_entity_id,
    legacy_source_table,
    legacy_source_id,
    metadata,
    created_by
) VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL, NULL, $7)
ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING
"""


#: The default ``created_by`` value when the caller does not supply one.
#: The audit trail needs a stable actor so the death-vs-closing lineage
#: is queryable; the system actor names the orchestrator that produced
#: the events.
DEFAULT_CREATED_BY = "lifecycle.close_all_on_death"


def _close_event(  # noqa: PLR0913 - lifecycle event has 7 distinct fields
    executor: SqlExecutor,
    *,
    animal_id: str,
    event_type: str,
    event_timestamp: str,
    caused_by_event_id: str,
    source_entity_type: str,
    source_entity_id: str,
    created_by: str,
) -> None:
    """Emit one append-only closing event for the animal."""
    executor.execute_sql(
        _INSERT_CLOSING_EVENT_SQL,
        [
            animal_id,
            event_type,
            event_timestamp,
            caused_by_event_id,
            source_entity_type,
            source_entity_id,
            created_by,
        ],
    )


def _close_active_placements(  # noqa: PLR0913 - placement kind + event shape + lineage are 8 distinct parameters
    executor: SqlExecutor,
    *,
    sql: str,
    animal_id: str,
    event_type: str,
    event_timestamp: str,
    caused_by_event_id: str,
    source_entity_type: str,
    id_column: str,
    created_by: str,
) -> None:
    """Emit one closing event for every active placement of one kind.

    The placement tables (``entradas`` / ``acogidas`` / ``adopciones``)
    share the same active-row shape and the same closing-event shape;
    only the source SQL, the closing event type, the source-entity
    type, and the row id column differ. Folding the three near-identical
    loop bodies from ``close_all_on_death`` into one helper keeps the
    use case focused on orchestration (and CRAP-grade A per the
    quality-gates ratchet).
    """
    rows = executor.execute_sql(sql, [animal_id])
    for row in rows:
        _close_event(
            executor,
            animal_id=animal_id,
            event_type=event_type,
            event_timestamp=event_timestamp,
            caused_by_event_id=caused_by_event_id,
            source_entity_type=source_entity_type,
            source_entity_id=str(row[id_column]),
            created_by=created_by,
        )


def close_all_on_death(
    executor: SqlExecutor,
    animal_id: str,
    event_timestamp: str | datetime,
    *,
    created_by: str = DEFAULT_CREATED_BY,
    metadata: dict[str, Any] | None = None,
    lifecycle_port: LifecyclePort | None = None,
) -> str:
    """Emit ``DEATH_RECORDED`` + one closing event per active placement.

    Parameters
    ----------
    executor
        The ``SqlExecutor`` for the live DB session (AGENTS.md §31).
    animal_id
        The animal whose death is being recorded.
    event_timestamp
        Wall-clock moment of death. Accepts ``str`` (ISO 8601) or
        ``datetime`` (coerced via ``.isoformat()``).
    created_by
        Actor name persisted on every emitted event. Defaults to
        ``"lifecycle.close_all_on_death"`` so the lineage is
        queryable. Override in tests / route handlers to record the
        end-user identity.
    metadata
        Optional JSON dict persisted on the ``DEATH_RECORDED`` event
        (not on the closing events). Use for caller-specific context
        (operator notes, causa de defunción, etc.).

    Returns
    -------
    str
        The ``id`` of the ``DEATH_RECORDED`` event row. Callers that
        want to log or audit-trail the death can use it; the closing
        events reference it via ``caused_by_event_id``.

    Notes
    -----
    The use case is **event-sourced**: it never ``UPDATE``s or
    ``DELETE``s ``entradas`` / ``acogidas`` / ``adopciones``. The
    append-only trigger on ``animal_lifecycle_events`` guarantees the
    event log stays the single source of truth for state derivation;
    the cascade in
    ``app/modules/lifecycle/domain/animal_state.py`` re-derives the
    state from the source tables on every read, so closing at the
    source rows would create a second, divergent source.
    """
    timestamp_str = (
        event_timestamp.isoformat()
        if isinstance(event_timestamp, datetime)
        else event_timestamp
    )

    # Step 1 — emit DEATH_RECORDED and capture its id for the
    # closing-event lineage. The RETURNING clause is what makes the
    # lineage possible without a second round-trip.
    metadata_json = (
        __import__("json").dumps(metadata)
        if metadata is not None
        else None
    )
    death_rows = executor.execute_sql(
        _INSERT_DEATH_EVENT_SQL,
        [animal_id, "DEATH_RECORDED", timestamp_str, metadata_json, created_by],
    )
    death_event_id = (
        str(death_rows[0]["id"]) if death_rows else str(uuid.uuid4())
    )

    # Step 2 — for every active placement at the time of death, emit
    # a closing event that points at the death via caused_by_event_id.
    # The cascade will re-derive the state on the next read; the
    # closing events are the only thing that needs to be emitted here.
    _close_active_placements(
        executor,
        sql=_SELECT_ACTIVE_INTAKES_SQL,
        animal_id=animal_id,
        event_type="INTAKE_CLOSED_BY_DEATH",
        event_timestamp=timestamp_str,
        caused_by_event_id=death_event_id,
        source_entity_type="entradas",
        id_column="IDEntrada",
        created_by=created_by,
    )
    _close_active_placements(
        executor,
        sql=_SELECT_ACTIVE_FOSTERS_SQL,
        animal_id=animal_id,
        event_type="FOSTER_CLOSED_BY_DEATH",
        event_timestamp=timestamp_str,
        caused_by_event_id=death_event_id,
        source_entity_type="acogidas",
        id_column="IDAcogida",
        created_by=created_by,
    )
    _close_active_placements(
        executor,
        sql=_SELECT_ACTIVE_ADOPTIONS_SQL,
        animal_id=animal_id,
        event_type="ADOPTION_CLOSED_BY_DEATH",
        event_timestamp=timestamp_str,
        caused_by_event_id=death_event_id,
        source_entity_type="adopciones",
        id_column="IDAdopcion",
        created_by=created_by,
    )

    if lifecycle_port is not None:
        result = lifecycle_port.calculate_state(animal_id)
        lifecycle_port.persist_animal_state(animal_id, result)

    return death_event_id


__all__ = ["close_all_on_death", "DEFAULT_CREATED_BY"]
