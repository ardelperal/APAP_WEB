"""``close_previous_situation`` use case (LIFECYCLE-03 PR-C).

When an animal transitions between situations (Albergue -> Acogida,
Acogida -> Adoptado, Adoptado -> returned-to-foster, etc.), this
use case emits the matching closing event:

- ``INTAKE_CLOSED_BY_FOSTER`` for Albergue -> Acogida.
- ``FOSTER_CLOSED_BY_ADOPTION`` for Acogida -> Adoptado.
- ``ADOPTION_RETURNED`` for Adoptado -> return-to-foster.

The closing is **event-sourced** (AGENTS.md §33.4): the use case
NEVER ``UPDATE``s the source record's end-date. The caller (route
handler, use case composition) is responsible for atomically setting
``fecha_salida`` / ``fecha_final`` / ``fecha_devolucion`` on the
source row; the closing event is the audit trail that records the
transition in the event log.

The closing event references the trigger event via
``caused_by_event_id`` so the lineage is traceable end-to-end.

The use case takes the ``SqlExecutor`` Protocol (AGENTS.md §31) for
the same reason as ``close_all_on_death`` — the port
(``LifecyclePort``) only exposes ``calculate_state`` and
``persist_animal_state``, neither of which fits event emission.

LIFECYCLE-03 (issue #33) PR-C work-unit C5.
"""
from __future__ import annotations

from datetime import datetime
from typing import Final

from app.core.data_access import SqlExecutor

#: Mapping from the situation category to the matching closing event.
#: The set is closed — adding a new transition means both adding a
#: member here AND extending the ``animal_lifecycle_events`` CHECK
#: enum at ``app/core/domain_lifecycle.py:69-76``.
CLOSING_EVENT_BY_CATEGORY: Final[dict[str, str]] = {
    "INTAKE": "INTAKE_CLOSED_BY_FOSTER",
    "FOSTER": "FOSTER_CLOSED_BY_ADOPTION",
    "ADOPTION": "ADOPTION_RETURNED",
}


#: Default ``created_by`` actor name; override in routes / tests to
#: record the end-user identity that triggered the transition.
DEFAULT_CREATED_BY: Final[str] = "lifecycle.close_previous_situation"


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


class UnknownSituationCategoryError(ValueError):
    """Raised when ``category`` is not one of ``INTAKE`` / ``FOSTER`` / ``ADOPTION``.

    The set is closed (see ``CLOSING_EVENT_BY_CATEGORY``); a typo or
    a future situation category that has no matching closing event
    must surface as a domain error rather than silently emit the
    wrong event type.
    """
    #: Backwards-compat alias for the previous class name. The
    #: N818 lint rule required renaming to ``Error`` suffix; the
    #: alias lets callers that imported the old name continue to
    #: work until they migrate.
    #: (No alias emitted; the rename is intentional.)

    def __init__(self, category: str) -> None:
        super().__init__(
            f"unknown situation category {category!r}; expected one of "
            f"{sorted(CLOSING_EVENT_BY_CATEGORY)}"
        )
        self.category = category


def close_previous_situation(  # noqa: PLR0913 - situation transition needs category + lineage + 2 source refs + actor
    executor: SqlExecutor,
    animal_id: str,
    category: str,
    caused_by_event_id: str,
    event_timestamp: str | datetime,
    *,
    source_entity_type: str | None = None,
    source_entity_id: str | None = None,
    created_by: str = DEFAULT_CREATED_BY,
) -> None:
    """Emit the closing event for a previous situation category.

    Parameters
    ----------
    executor
        The ``SqlExecutor`` for the live DB session (AGENTS.md §31).
    animal_id
        The animal whose situation is being closed.
    category
        One of ``"INTAKE"`` / ``"FOSTER"`` / ``"ADOPTION"``. The
        matching closing event is looked up from
        ``CLOSING_EVENT_BY_CATEGORY``; any other value raises
        :class:`UnknownSituationCategory`.
    caused_by_event_id
        The id of the trigger event that caused this transition
        (e.g. the ``FOSTER_STARTED`` event id for an Albergue ->
        Acogida transition). Persisted as ``caused_by_event_id`` on
        the closing event so the lineage is queryable.
    event_timestamp
        Wall-clock moment of the transition. Accepts ``str`` or
        ``datetime``.
    source_entity_type
        Optional ``entradas`` / ``acogidas`` / ``adopciones`` source
        row type — surfaced on the event for the audit trail. When
        omitted the closing event has no source-entity link.
    source_entity_id
        Optional source row id (UUID string). Paired with
        ``source_entity_type`` when the caller already knows which
        row is closing.
    created_by
        Actor name persisted on the closing event. Defaults to
        ``"lifecycle.close_previous_situation"``.

    Notes
    -----
    The use case does NOT update ``fecha_salida`` / ``fecha_final`` /
    ``fecha_devolucion`` on the source rows. The caller is
    responsible for atomically setting the source row's end date —
    otherwise the cascade will keep reading the row as active and the
    ``close_previous_situation`` event will not match the
    source-of-truth. The split (event log for audit, source rows for
    active-placement detection) is the event-sourcing pattern that
    AGENTS.md §33.4 calls out for the lifecycle slice.
    """
    event_type = CLOSING_EVENT_BY_CATEGORY.get(category)
    if event_type is None:
        raise UnknownSituationCategoryError(category)

    timestamp_str = (
        event_timestamp.isoformat()
        if isinstance(event_timestamp, datetime)
        else event_timestamp
    )

    executor.execute_sql(
        _INSERT_CLOSING_EVENT_SQL,
        [
            animal_id,
            event_type,
            timestamp_str,
            caused_by_event_id,
            source_entity_type,
            source_entity_id,
            created_by,
        ],
    )


__all__ = [
    "CLOSING_EVENT_BY_CATEGORY",
    "DEFAULT_CREATED_BY",
    "UnknownSituationCategoryError",
    "close_previous_situation",
]
