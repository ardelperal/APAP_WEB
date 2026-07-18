"""Semantic events translator — diff → ``animal_lifecycle_events``.

PR 2 of ``web-only-feature-preservation``. Translates legacy diffs
(INERT/UPDATE on the 4 lifecycle tables) into ``LifecycleEvent``
records the applier (PR 4) persists into ``animal_lifecycle_events``.

This module is INTENTIONALLY independent of ``diff_engine.DiffEngine``
(design §5 — Q3). It imports only the ``Diff`` dataclass from
``reporting.py`` and the ``TableMapping`` from ``mappings``. The
translator is a pure function with no I/O; the caller (PR 4's hook)
owns the persistence path.

PR6 / M2 adds the symmetric ``LIFECYCLE_REVERSED`` event for the
reverse path: when a derived column (``current_state``) was overridden
in web between forward and reverse apply, the reverse applier emits
a ``LIFECYCLE_REVERSED`` event carrying ``source_direction="web-to-legacy"``,
the pre/post states, and the legacy source PK so the operator CLI can
render the transition log without a second pass through the
derivation engine.

Mapping table (8 combinations, design §5 + lifecycle-event-log-design §4):

| Legacy table        | op     | Field transition                | Event              |
|---------------------|--------|---------------------------------|--------------------|
| ``TbEntradas``      | INSERT | ``FEntrada NOT NULL``           | ``INTAKE_STARTED`` |
| ``TbEntradas``      | UPDATE | ``FSalida: NULL → date``        | ``INTAKE_COMPLETED``|
| ``TbEntradas``      | UPDATE | ``FEntregaAPropietario: NULL → date`` | ``OWNER_RETURNED`` |
| ``TbAcogidaAnimal`` | INSERT | —                               | ``FOSTER_STARTED`` |
| ``TbAcogidaAnimal`` | UPDATE | ``FFinal: NULL → date``         | ``FOSTER_RETURNED``|
| ``TbAdopcion``      | INSERT | —                               | ``ADOPTION_STARTED``|
| ``TbAdopcion``      | UPDATE | ``FDevolucion: NULL → date``     | ``ADOPTION_RETURNED``|
| ``TbFichaAnimal``   | UPDATE | ``FDefuncion: NULL → date``     | ``DEATH_RECORDED`` |
| *(reverse path)*    | UPDATE | ``pre_state`` ≠ ``post_state`` (derived column override in web) | ``LIFECYCLE_REVERSED`` |
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from migration.mappings import TableMapping
from migration.reporting import Diff

# --- LifecycleEvent -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """One lifecycle event inferred from a legacy diff.

    Mirrors the relevant fields of ``animal_lifecycle_events`` so the
    applier (PR 4) can persist the result without an extra mapping
    step. The fields the legacy diff does not provide
    (``animal_id``, ``created_by``, ``created_at``) are NOT on this
    dataclass — the applier fills them in at INSERT time.

    ``metadata`` carries per-event-type context. Today it is populated
    only for ``DEATH_RECORDED`` (pre_death_state) so the applier can
    mass-close the active records timestamped at the death date.
    """

    event_type: str
    event_timestamp: datetime
    legacy_source_table: str
    legacy_source_id: int | None
    source_entity_type: str | None = None
    metadata: dict[str, Any] | None = None


# --- Public entry point ---------------------------------------------------


def translate_diff(diff: Diff, table_mapping: TableMapping) -> list[LifecycleEvent]:
    """Translate one legacy diff into 0..n lifecycle events.

    Returns an empty list for diffs that don't trigger any event
    (NOOP, DELETE, INSERT in a non-lifecycle table, UPDATE without any
    relevant field change). The translator is a pure function — no
    I/O, no side effects. The caller (PR 4's applier hook) is
    responsible for INSERTing the returned events into
    ``animal_lifecycle_events``.

    ``table_mapping.legacy_table`` is the ONLY field of the mapping
    the translator reads; the rest of the mapping is intentionally
    unused so the translator stays decoupled from PR 3's YAML
    machinery.
    """
    legacy_table = table_mapping.legacy_table

    if diff.op == "INSERT":
        return _translate_insert(diff, legacy_table)
    if diff.op == "UPDATE":
        return _translate_update(diff, legacy_table)
    # NOOP, DELETE, or anything else → no event.
    return []


# --- INSERT handlers ------------------------------------------------------


def _translate_insert(diff: Diff, legacy_table: str) -> list[LifecycleEvent]:
    """Translate an INSERT diff on a lifecycle table.

    Each branch returns at most one event. INSERTs on
    ``TbFichaAnimal`` don't directly produce events (the ficha is
    created at registration, before any lifecycle action).
    """
    if legacy_table == "TbEntradas":
        timestamp = _read_timestamp(diff.legacy_row, "FEntrada")
        if timestamp is None:
            return []
        return [
            LifecycleEvent(
                event_type="INTAKE_STARTED",
                event_timestamp=timestamp,
                legacy_source_table="TbEntradas",
                legacy_source_id=_read_int(diff.legacy_row, "IDEntrada"),
                source_entity_type="intake",
            )
        ]

    if legacy_table == "TbAcogidaAnimal":
        timestamp = _read_timestamp(diff.legacy_row, "FInicio")
        if timestamp is None:
            return []
        return [
            LifecycleEvent(
                event_type="FOSTER_STARTED",
                event_timestamp=timestamp,
                legacy_source_table="TbAcogidaAnimal",
                legacy_source_id=_read_int(diff.legacy_row, "IDAcogida"),
                source_entity_type="foster",
            )
        ]

    if legacy_table == "TbAdopcion":
        timestamp = _read_timestamp(diff.legacy_row, "FAdopcion")
        if timestamp is None:
            return []
        return [
            LifecycleEvent(
                event_type="ADOPTION_STARTED",
                event_timestamp=timestamp,
                legacy_source_table="TbAdopcion",
                legacy_source_id=_read_int(diff.legacy_row, "IDAdopcion"),
                source_entity_type="adoption",
            )
        ]

    # ``TbFichaAnimal`` INSERT → no lifecycle event (registration is
    # not a lifecycle transition). DELETE also covered here because it
    # would land in the ``return []`` arm above.
    return []


# --- UPDATE handlers ------------------------------------------------------


def _translate_update(diff: Diff, legacy_table: str) -> list[LifecycleEvent]:
    """Translate an UPDATE diff on a lifecycle table.

    The translator inspects the post-update ``legacy_row``; the
    ``changed_fields`` tuple from the diff is informational only
    (the diff engine already filtered on what changed). Each branch
    returns at most one event today — the spec defines a 1:1 mapping
    for the 8 combinations.
    """
    if legacy_table == "TbEntradas":
        return _translate_update_entrada(diff)
    if legacy_table == "TbAcogidaAnimal":
        return _translate_update_acogida(diff)
    if legacy_table == "TbAdopcion":
        return _translate_update_adopcion(diff)
    if legacy_table == "TbFichaAnimal":
        return _translate_update_ficha(diff)
    return []


def _translate_update_entrada(diff: Diff) -> list[LifecycleEvent]:
    """TbEntradas UPDATE — distinguishes INTAKE_COMPLETED vs OWNER_RETURNED.

    The owner-return path takes precedence: when both ``FSalida`` and
    ``FEntregaAPropietario`` are set in the post-update row, the
    legacy semantics is OWNER_RETURNED (the animal went home, not just
    left the shelter). The applier only needs the terminal event for
    its reconciliation pass.
    """
    row = diff.legacy_row or {}

    # FEntregaAPropietario: NULL → date → OWNER_RETURNED (terminal).
    timestamp = _read_timestamp(row, "FEntregaAPropietario")
    if timestamp is not None:
        return [
            LifecycleEvent(
                event_type="OWNER_RETURNED",
                event_timestamp=timestamp,
                legacy_source_table="TbEntradas",
                legacy_source_id=_read_int(row, "IDEntrada"),
                source_entity_type="intake",
            )
        ]

    # FSalida: NULL → date (without owner return) → INTAKE_COMPLETED.
    timestamp = _read_timestamp(row, "FSalida")
    if timestamp is not None:
        return [
            LifecycleEvent(
                event_type="INTAKE_COMPLETED",
                event_timestamp=timestamp,
                legacy_source_table="TbEntradas",
                legacy_source_id=_read_int(row, "IDEntrada"),
                source_entity_type="intake",
            )
        ]

    return []


def _translate_update_acogida(diff: Diff) -> list[LifecycleEvent]:
    """TbAcogidaAnimal UPDATE — FFinal NULL → date → FOSTER_RETURNED."""
    row = diff.legacy_row or {}
    timestamp = _read_timestamp(row, "FFinal")
    if timestamp is None:
        return []
    return [
        LifecycleEvent(
            event_type="FOSTER_RETURNED",
            event_timestamp=timestamp,
            legacy_source_table="TbAcogidaAnimal",
            legacy_source_id=_read_int(row, "IDAcogida"),
            source_entity_type="foster",
        )
    ]


def _translate_update_adopcion(diff: Diff) -> list[LifecycleEvent]:
    """TbAdopcion UPDATE — FDevolucion NULL → date → ADOPTION_RETURNED."""
    row = diff.legacy_row or {}
    timestamp = _read_timestamp(row, "FDevolucion")
    if timestamp is None:
        return []
    return [
        LifecycleEvent(
            event_type="ADOPTION_RETURNED",
            event_timestamp=timestamp,
            legacy_source_table="TbAdopcion",
            legacy_source_id=_read_int(row, "IDAdopcion"),
            source_entity_type="adoption",
        )
    ]


def _translate_update_ficha(diff: Diff) -> list[LifecycleEvent]:
    """TbFichaAnimal UPDATE — FDefuncion NULL → date → DEATH_RECORDED.

    The pre-death state (``UltimoEstadoAntesDeFallecido``) is captured
    in ``metadata`` so the applier (PR 4) can mass-close the active
    records timestamped at the death date without a second pass
    through the derivation engine.

    ``legacy_source_id`` is intentionally ``None`` for ``DEATH_RECORDED``:
    ``TbFichaAnimal.key_field`` (= ``NCHIP``) is a free-text string
    in the mapping (``app/core/migration/mappings/animal.yaml``) and
    cannot be coerced to ``int`` (real APAP chips include alphanumeric
    forms like ``"2030A"``, ``"ES-12345"`` and numeric-looking labels
    like ``"001"`` whose leading zero is part of the identity). The
    chip is already on the parent FK ``animal_id`` after PR 4 resolves
    it, so the event itself does not need to carry an int-coerced
    NCHIP. The applier hydrates ``legacy_source_id`` from the FK
    during the insert into ``animal_lifecycle_events``.
    """
    row = diff.legacy_row or {}
    timestamp = _read_timestamp(row, "FDefuncion")
    if timestamp is None:
        return []
    pre_death_state = row.get("UltimoEstadoAntesDeFallecido")
    metadata: dict[str, Any] = {}
    if pre_death_state:
        metadata["pre_death_state"] = pre_death_state
    return [
        LifecycleEvent(
            event_type="DEATH_RECORDED",
            event_timestamp=timestamp,
            legacy_source_table="TbFichaAnimal",
            legacy_source_id=None,
            source_entity_type="death",
            metadata=metadata or None,
        )
    ]


# --- helpers --------------------------------------------------------------


def _read_timestamp(row: dict[str, Any] | None, field: str) -> datetime | None:
    """Return ``row[field]`` coerced to a tz-aware ``datetime``, or ``None``.

    Accepts ``datetime`` (kept as-is, tz-aware ensured), non-empty
    strings (parsed as ISO-8601), and treats ``None`` / empty string
    as ``None`` (the legacy "no date set" signal). Raises ``ValueError``
    on unparseable strings so a malformed legacy value is NOT
    silently dropped — the applier will surface it through the
    ``MigrationReport.reconciliation_errors`` field.
    """
    if not row:
        return None
    raw = row.get(field)
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(
                f"Cannot parse legacy {field!r} value {raw!r} as ISO-8601 datetime: {exc}"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    raise ValueError(
        f"Cannot coerce legacy {field!r} value of type "
        f"{type(raw).__name__!r} into a datetime; expected datetime or ISO-8601 string"
    )


def _read_int(row: dict[str, Any] | None, field: str) -> int | None:
    """Return ``row[field]`` coerced to ``int`` (or ``None`` when missing)."""
    if not row:
        return None
    raw = row.get(field)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot coerce legacy {field!r} value {raw!r} into int") from exc


__all__ = [
    "LIFECYCLE_REVERSED_SOURCE_DIRECTION",
    "LifecycleEvent",
    "record_lifecycle_reversed",
    "translate_diff",
]


# --- LIFECYCLE_REVERSED emitter (PR6 / M2 reverse path) ------------------
#
# The reverse applier (web -> legacy) observes a derived-column state
# change (``animal_current_state.current_state`` was overridden in web
# between forward and reverse apply) and emits a ``LIFECYCLE_REVERSED``
# event with pre/post states and ``source_direction="web-to-legacy"``.
# The semantic surface is intentionally narrow: the reverse applier
# calls this once per state-change row; everything else stays the same
# as the forward path (no re-derivation, no DDL, no I/O).


LIFECYCLE_REVERSED_SOURCE_DIRECTION = "web-to-legacy"


def record_lifecycle_reversed(
    *,
    pre_state,
    post_state,
    legacy_source_table,
    legacy_source_id,
    occurred_at=None,
):
    """Emit a ``LIFECYCLE_REVERSED`` event for the reverse applier.

    PR6 spec scenario: Web->legacy emits LIFECYCLE_REVERSED event for
    animal state. The reverse applier (``migration.apply_reverse``)
    calls this once per derived-column state change it observes between
    forward and reverse apply.

    Args:
        pre_state: the ``current_state`` derived by the prior forward
            apply. May be None (the row never had a state machine
            attached) -- kept verbatim on the event so the operator
            CLI can render "before / after" even on null->string
            transitions.
        post_state: the ``current_state`` observed in web post-override.
            Required for the event to be meaningful; the reverse applier
            only emits when the two values differ.
        legacy_source_table: the YAML legacy table the row belongs to
            (e.g. ``"TbFichaAnimal"``). Mirrors the forward path's
            ``legacy_source_table`` field on ``LifecycleEvent``.
        legacy_source_id: the legacy PK as int (when coercible). None
            for free-text chips (``TbFichaAnimal.key_field`` is string);
            the applier hydrates ``animal_id`` from the FK at INSERT
            time.
        occurred_at: UTC timestamp stamped on the event. Defaults to
            ``datetime.now(UTC)`` so callers can pass ``None`` and let
            the helper stamp a fresh value.

    Returns:
        The constructed :class:`LifecycleEvent`. The reverse applier
        does not persist the result directly -- it forwards the event
        to the same lifecycle-event ingestion path the forward
        applier uses (``animal_lifecycle_events`` INSERT).
    """
    ts = occurred_at if occurred_at is not None else datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    metadata = {
        "pre_state": pre_state,
        "post_state": post_state,
        "source_direction": LIFECYCLE_REVERSED_SOURCE_DIRECTION,
    }
    return LifecycleEvent(
        event_type="LIFECYCLE_REVERSED",
        event_timestamp=ts,
        legacy_source_table=legacy_source_table,
        legacy_source_id=legacy_source_id,
        source_entity_type="state_reversal",
        metadata=metadata,
    )
