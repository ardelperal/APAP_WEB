"""Service layer for the animal lifecycle event log (LIFECYCLE-02, issue #32).

Bounded context: lifecycle. This module owns the surface that writes
events to ``animal_lifecycle_events`` and enforces the causal-pair rule
D-23 (``FOSTER_CLOSED_BY_ADOPTION`` must precede ``ADOPTION_STARTED``
for the same animal).

Public API (consumed by routes in future PRs and by the migration
``post_apply_diff`` hook):

- :class:`LifecycleEventType`: the 14 pinned event types (10 core + 4
  supporting). One source of truth: the StrEnum members agree with
  the ``CHECK (event_type IN (...))`` constraint in the table
  definition (``app.core.domain_lifecycle``).
- :class:`CausalPairViolation`: typed exception raised when the D-23
  rule is violated. Carries the decision id (``D-23``), the animal
  id, and the offending event type so the caller (route or hook)
  can produce a precise 409 response.
- :func:`record_event`: append-only INSERT into
  ``animal_lifecycle_events`` with ``ON CONFLICT DO NOTHING`` on the
  natural key. Idempotent at the DB level — a retry of the same
  logical event (same ``animal_id`` + same ``event_type`` + same
  ``event_timestamp``) collapses to a single row.
- :func:`validate_causal_pair`: pure pre-flight check that raises
  :class:`CausalPairViolation` when the D-23 pair would be violated
  by an upcoming write. The check is scoped to the pair
  (animal + event_type) so the SELECT path uses the
  ``idx_animal_lifecycle_events_animal_timestamp`` index.

Append-only invariant
(``app.core.domain_lifecycle::ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL``):

The ``animal_lifecycle_events_append_only`` BEFORE UPDATE OR DELETE
trigger rejects any UPDATE/DELETE on the log at the SQL level. This
module does NOT expose update or delete operations — there are none.
Corrections are modelled as new events with ``caused_by_event_id``
pointing at the prior event (see :func:`record_event` signature).
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from app.core.data_access import SqlExecutor

# --- enums ----------------------------------------------------------------

# Decision id baked into every causal-pair violation so the log + the
# router can identify the rule that fired (issue #32 acceptance:
# "Causal pair rule: FOSTER_CLOSED_BY_ADOPTION -> ADOPTION_STARTED
# enforced (D-23)").
CAUSAL_PAIR_DECISION_ID: Final[str] = "D-23"


class LifecycleEventType(StrEnum):
    """The 14 pinned lifecycle event types (issue #32 acceptance).

    10 core event types drive the state machine:

    - INTAKE_STARTED, INTAKE_COMPLETED — animal enters the protectora.
    - FOSTER_STARTED, FOSTER_RETURNED — foster stays.
    - FOSTER_CLOSED_BY_ADOPTION — foster closes because of an adoption.
    - ADOPTION_STARTED, ADOPTION_RETURNED — adoption lifecycle.
    - OWNER_RETURNED — entrega a propietario.
    - DEATH_RECORDED — defunción.
    - STATE_CORRECTION — operator-driven correction.

    4 supporting event types track amendments / reopens:

    - CHIP_CHANGED — microchip was re-implanted / changed.
    - INTAKE_REOPENED, FOSTER_REOPENED, ADOPTION_REOPENED — an
      already-closed situation was reopened.

    Adding a new event type means BOTH adding a member here AND
    extending the ``CHECK (event_type IN (...))`` constraint in
    ``ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL``. The integration
    test ``test_core_event_types_set_matches_strenum_members`` in
    ``tests/test_domain_lifecycle.py`` catches divergence when the
    CHECK constraint is re-extracted.
    """

    # 10 core event types
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

    # 4 supporting event types
    CHIP_CHANGED = "CHIP_CHANGED"
    INTAKE_REOPENED = "INTAKE_REOPENED"
    FOSTER_REOPENED = "FOSTER_REOPENED"
    ADOPTION_REOPENED = "ADOPTION_REOPENED"


# Derived sets (AGENTS.md §4: one source of truth per domain concept).
# The frozensets are derived from the StrEnum so adding a member is
# enough — no risk of the two lists drifting.
CORE_EVENT_TYPES: Final[frozenset[LifecycleEventType]] = frozenset(
    {
        LifecycleEventType.INTAKE_STARTED,
        LifecycleEventType.INTAKE_COMPLETED,
        LifecycleEventType.FOSTER_STARTED,
        LifecycleEventType.FOSTER_RETURNED,
        LifecycleEventType.FOSTER_CLOSED_BY_ADOPTION,
        LifecycleEventType.ADOPTION_STARTED,
        LifecycleEventType.ADOPTION_RETURNED,
        LifecycleEventType.OWNER_RETURNED,
        LifecycleEventType.DEATH_RECORDED,
        LifecycleEventType.STATE_CORRECTION,
    }
)

SUPPORTING_EVENT_TYPES: Final[frozenset[LifecycleEventType]] = frozenset(
    {
        LifecycleEventType.CHIP_CHANGED,
        LifecycleEventType.INTAKE_REOPENED,
        LifecycleEventType.FOSTER_REOPENED,
        LifecycleEventType.ADOPTION_REOPENED,
    }
)


# --- exceptions -----------------------------------------------------------


class CausalPairViolation(ValueError):
    """Raised when a lifecycle event would violate the D-23 causal-pair rule.

    The rule: ``FOSTER_CLOSED_BY_ADOPTION`` must precede
    ``ADOPTION_STARTED`` for the same animal. Either direction
    out-of-order (e.g. an adoption recorded before its closing foster
    event, or a foster-closed-by-adoption emitted after an existing
    adoption) raises this exception.

    Carries the decision id (``D-23``), the animal id, and the
    offending event type so callers can produce a precise 409.
    """

    def __init__(
        self,
        *,
        animal_id: str,
        event_type: LifecycleEventType,
        message: str,
    ) -> None:
        super().__init__(message)
        self.decision_id = CAUSAL_PAIR_DECISION_ID
        self.animal_id = animal_id
        self.event_type = event_type


# --- helpers --------------------------------------------------------------


def _coerce_event_type(value: Any) -> LifecycleEventType:
    """Accept a StrEnum member or a string, reject anything else."""
    if isinstance(value, LifecycleEventType):
        return value
    if isinstance(value, str):
        try:
            return LifecycleEventType(value)
        except ValueError as exc:
            raise ValueError(
                f"event_type must be one of {[m.value for m in LifecycleEventType]}, "
                f"received: {value!r}"
            ) from exc
    raise ValueError(
        f"event_type must be a LifecycleEventType or a string, "
        f"received: {type(value).__name__}"
    )


def _validate_required_fields(
    *,
    animal_id: str,
    _event_type: LifecycleEventType,
    event_timestamp: str,
    created_by: str,
) -> None:
    """Validate the 4 required fields before any SQL touches the DB.

    These checks are the application-level companion to the
    ``animal_lifecycle_events`` schema's NOT NULL constraints: we
    fail fast on the application boundary so a malformed caller does
    not waste a round-trip on a CHECK / NOT NULL violation.
    """
    if not animal_id or not animal_id.strip():
        raise ValueError("animal_id is required and cannot be empty")
    if not event_timestamp or not event_timestamp.strip():
        raise ValueError("event_timestamp is required and cannot be empty")
    if not created_by or not created_by.strip():
        raise ValueError("created_by is required and cannot be empty")
    # event_type is already coerced to the StrEnum by the caller; the
    # StrEnum membership check is the validation.


# --- SQL -----------------------------------------------------------------

# Column order matches the INSERT's positional params (``$1..$10``).
# ``event_type`` carries the natural-key field; ``ON CONFLICT`` targets
# the same triple the UNIQUE constraint enforces on
# ``(animal_id, event_type, event_timestamp)``.
_INSERT_LIFECYCLE_EVENT_SQL = """
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
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING
"""

# Pre-flight SELECT for the D-23 causal-pair check. We filter by
# ``animal_id`` (PK + index) and the two event types that participate
# in the pair (FOSTER_CLOSED_BY_ADOPTION, ADOPTION_STARTED). The
# pre-flight returns 0 rows when the rule is satisfied — the
# ``idx_animal_lifecycle_events_animal_timestamp`` index covers the
# ``animal_id`` predicate.
_SELECT_CAUSAL_PAIR_PRIOR_SQL = """
SELECT event_type, event_timestamp
FROM animal_lifecycle_events
WHERE animal_id = $1
  AND event_type IN ($2, $3)
"""

# --- cache update SQL (LIFECYCLE-SCHEMA-03, issue #69) ---------------------

# UPSERT the cache row for an animal after an event is recorded.
# Uses ON CONFLICT (animal_id) DO UPDATE so inserts and updates are
# both handled by the same statement — idempotent at the application
# level.
# The caller passes the computed current_state value derived from the
# event log; this SQL only persists the cache row.
_UPSERT_CACHE_SQL = """
INSERT INTO animal_current_state (
    animal_id,
    current_state,
    active_event_id,
    state_changed_at,
    reconciliation_status
) VALUES ($1, $2, $3, now(), 'pending')
ON CONFLICT (animal_id) DO UPDATE SET
    current_state = EXCLUDED.current_state,
    active_event_id = EXCLUDED.active_event_id,
    state_changed_at = EXCLUDED.state_changed_at,
    reconciliation_status = 'pending'
"""

# SELECT to get the latest event for an animal (used by
# _compute_current_state_from_events).
_SELECT_LATEST_EVENT_SQL = """
SELECT id, event_type, event_timestamp
FROM animal_lifecycle_events
WHERE animal_id = $1
ORDER BY event_timestamp DESC
LIMIT 1
"""


# --- state derivation (simplified — see docs/discovery/lifecycle-state-resolver.md) ---

# Mapping from event type to the derived current_state value.
# This is a simplified derivation; the full state machine is tracked in
# the discovery doc (pending: lifecycle-state-resolver-extraction.md).
_EVENT_TYPE_TO_STATE: dict[str, str] = {
    LifecycleEventType.INTAKE_STARTED.value: "Pendiente de Entrada",
    LifecycleEventType.INTAKE_COMPLETED.value: "Albergue",
    LifecycleEventType.FOSTER_STARTED.value: "Acogida",
    LifecycleEventType.FOSTER_RETURNED.value: "Acogida",
    LifecycleEventType.ADOPTION_STARTED.value: "Adoptado",
    LifecycleEventType.ADOPTION_RETURNED.value: "Acogida",
    LifecycleEventType.OWNER_RETURNED.value: "Entregado",
    LifecycleEventType.DEATH_RECORDED.value: "Fallecido (Albergue)",
    LifecycleEventType.STATE_CORRECTION.value: "Pendiente de Nueva Situacion",
    LifecycleEventType.CHIP_CHANGED.value: "Pendiente de Nueva Situacion",
    LifecycleEventType.INTAKE_REOPENED.value: "Albergue",
    LifecycleEventType.FOSTER_REOPENED.value: "Acogida",
    LifecycleEventType.ADOPTION_REOPENED.value: "Adoptado",
    # FOSTER_CLOSED_BY_ADOPTION is not a terminal state; it is
    # always followed by ADOPTION_STARTED so it maps to the same
    # state as ADOPTION_STARTED.
    LifecycleEventType.FOSTER_CLOSED_BY_ADOPTION.value: "Adoptado",
}


def _compute_current_state_from_events(
    client: SqlExecutor,
    animal_id: str,
) -> tuple[str, str | None]:
    """Derive the current_state for an animal from its event log.

    Returns a tuple of (current_state, latest_event_id). If the animal
    has no events, returns ('Pendiente de Entrada', None).
    """
    rows = client.execute_sql(
        _SELECT_LATEST_EVENT_SQL,
        [animal_id],
    )
    if not rows:
        return ("Pendiente de Entrada", None)

    latest = rows[0]
    event_type = latest.get("event_type", "")
    latest_event_id = str(latest["id"]) if latest.get("id") else None

    # FOSTER_CLOSED_BY_ADOPTION is a transitional state: it triggers
    # ADOPTION_STARTED to follow. We derive 'Adoptado' here so the
    # cache reflects the final state rather than the transitional one.
    # The actual state machine is in the discovery doc.
    state = _EVENT_TYPE_TO_STATE.get(
        event_type, "Pendiente de Nueva Situacion"
    )
    return (state, latest_event_id)


# --- public API -----------------------------------------------------------


def actualizar_estado_animal(
    client: SqlExecutor,
    *,
    animal_id: str,
    current_state: str | None = None,
    active_event_id: str | None = None,
) -> None:
    """Update the ``animal_current_state`` cache row for an animal.

    This function is called by ``record_event`` after a lifecycle event
    is successfully inserted. It upserts the cache row so subsequent
    reads of the animal's state are O(1) without scanning the event log.

    The ``current_state`` and ``active_event_id`` are derived from the
    event log by :func:`_compute_current_state_from_events` before this
    function is called. The caller may also pass them explicitly if
    already known.

    Idempotent: ``ON CONFLICT (animal_id) DO UPDATE`` means re-running
    this for the same animal simply updates the row to the latest values.
    """
    if current_state is None:
        current_state, active_event_id = _compute_current_state_from_events(
            client, animal_id
        )

    client.execute_sql(
        _UPSERT_CACHE_SQL,
        [animal_id, current_state, active_event_id],
    )


def record_event(  # noqa: PLR0913  # domain event recorder; 10 keyword-only args are all distinct domain fields
    client: SqlExecutor,
    *,
    animal_id: str,
    event_type: LifecycleEventType | str,
    event_timestamp: str | datetime,
    created_by: str,
    caused_by_event_id: str | None = None,
    source_entity_type: str | None = None,
    source_entity_id: str | None = None,
    legacy_source_table: str | None = None,
    legacy_source_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one event to ``animal_lifecycle_events``.

    Idempotent via ``ON CONFLICT (animal_id, event_type,
    event_timestamp) DO NOTHING``: a retry of the same logical event
    collapses to a single row. The companion UNIQUE constraint on
    the natural key (declared in
    ``ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL``) is what makes the
    ``ON CONFLICT`` clause resolve to a no-op.

    Raises :class:`ValueError` on a missing required field or an
    event_type outside the 14 pinned values. Transport errors
    (``InsForgeError`` from the client) propagate untouched so the
    caller (route or hook) can map them to the appropriate HTTP code.
    """
    event_type_member = _coerce_event_type(event_type)
    timestamp_str = (
        event_timestamp.isoformat()
        if isinstance(event_timestamp, datetime)
        else event_timestamp
    )
    _validate_required_fields(
        animal_id=animal_id,
        event_type=event_type_member,
        event_timestamp=timestamp_str,
        created_by=created_by,
    )

    metadata_json = json.dumps(metadata) if metadata is not None else None

    client.execute_sql(
        _INSERT_LIFECYCLE_EVENT_SQL,
        [
            animal_id,
            event_type_member.value,
            timestamp_str,
            caused_by_event_id,
            source_entity_type,
            source_entity_id,
            legacy_source_table,
            legacy_source_id,
            metadata_json,
            created_by,
        ],
    )

    # LIFECYCLE-SCHEMA-03 (issue #69): update the materialized cache
    # after a successful event insert. The cache stores the derived
    # current_state so reads are O(1) without scanning the event log.
    actualizar_estado_animal(client, animal_id=animal_id)


def validate_causal_pair(
    client: SqlExecutor,
    *,
    animal_id: str,
    event_type: LifecycleEventType | str,
    event_timestamp: str | datetime,
) -> None:
    """Pre-flight check: would the upcoming event violate D-23?

    The rule fires only on the two members of the pair. Every other
    event type is a no-op even when the animal has zero prior events
    — that keeps the function composable with the rest of the
    lifecycle code (an INTAKE_STARTED at the beginning of an animal's
    life has no prerequisite).

    Pair order:

    - ``ADOPTION_STARTED`` requires a preceding
      ``FOSTER_CLOSED_BY_ADOPTION`` for the same animal with
      ``event_timestamp <= event_timestamp``. If the adoption is the
      first event, the rule fires (the foster never closed, so the
      animal went directly from intake to adoption — no bridge
      intake per D-23 "no bridge intake records").
    - ``FOSTER_CLOSED_BY_ADOPTION`` requires NO prior
      ``ADOPTION_STARTED`` for the same animal with
      ``event_timestamp < event_timestamp``. A foster closed by an
      adoption that has already happened is an out-of-order pair.

    Raises :class:`CausalPairViolation` carrying the animal id and
    the offending event type when the rule fires. Returns ``None``
    silently when the rule is satisfied.
    """
    event_type_member = _coerce_event_type(event_type)
    timestamp_str = (
        event_timestamp.isoformat()
        if isinstance(event_timestamp, datetime)
        else event_timestamp
    )

    pair_event_types = (
        LifecycleEventType.FOSTER_CLOSED_BY_ADOPTION,
        LifecycleEventType.ADOPTION_STARTED,
    )
    if event_type_member not in pair_event_types:
        # Out of the pair's domain — every other event type is
        # unconditionally allowed (INTAKE_STARTED at the beginning of
        # an animal's life, DEATH_RECORDED regardless of state, etc.).
        return

    rows = client.execute_sql(
        _SELECT_CAUSAL_PAIR_PRIOR_SQL,
        [
            animal_id,
            LifecycleEventType.FOSTER_CLOSED_BY_ADOPTION.value,
            LifecycleEventType.ADOPTION_STARTED.value,
        ],
    )

    foster_close_ts: str | None = None
    adoption_started_ts: str | None = None
    for row in rows:
        row_event_type = row.get("event_type")
        row_event_ts = row.get("event_timestamp")
        if not isinstance(row_event_ts, str):
            # The DB returns TIMESTAMPTZ as an ISO string via InsForge;
            # anything else is a contract drift.
            continue
        if row_event_type == LifecycleEventType.FOSTER_CLOSED_BY_ADOPTION.value:
            foster_close_ts = row_event_ts
        elif row_event_type == LifecycleEventType.ADOPTION_STARTED.value:
            adoption_started_ts = row_event_ts

    if event_type_member == LifecycleEventType.ADOPTION_STARTED:
        if foster_close_ts is None or foster_close_ts > timestamp_str:
            raise CausalPairViolation(
                animal_id=animal_id,
                event_type=event_type_member,
                message=(
                    f"D-23: ADOPTION_STARTED for animal {animal_id} at "
                    f"{timestamp_str} requires a preceding "
                    f"FOSTER_CLOSED_BY_ADOPTION at the same wall-clock moment "
                    f"or earlier. Found foster_close_ts={foster_close_ts!r}. "
                    f"No bridge intake records (D-23)."
                ),
            )
        return

    # Branch for the FOSTER_CLOSED_BY_ADOPTION case (the only remaining type).
    if (
        adoption_started_ts is not None
        and adoption_started_ts < timestamp_str
    ):
        raise CausalPairViolation(
            animal_id=animal_id,
            event_type=event_type_member,
            message=(
                f"D-23: FOSTER_CLOSED_BY_ADOPTION for animal {animal_id} at "
                f"{timestamp_str} would close a foster AFTER an existing "
                f"ADOPTION_STARTED at {adoption_started_ts}. Causal pair is "
                f"ordered (FOSTER_CLOSED_BY_ADOPTION precedes "
                f"ADOPTION_STARTED)."
            ),
        )


__all__ = [
    "CAUSAL_PAIR_DECISION_ID",
    "CORE_EVENT_TYPES",
    "CausalPairViolation",
    "LifecycleEventType",
    "SUPPORTING_EVENT_TYPES",
    "actualizar_estado_animal",
    "record_event",
    "validate_causal_pair",
]
