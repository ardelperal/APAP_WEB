"""Use-case tests for ``close_all_on_death`` (LIFECYCLE-03 PR-C).

The use case is event-sourced (AGENTS.md §22, §33.4): it emits
append-only events on ``animal_lifecycle_events`` for every active
placement at the time of death, and never issues UPDATE against
``entradas`` / ``acogidas`` / ``adopciones``. The append-only trigger
defined at ``app/core/domain_lifecycle.py:130-141`` is what makes the
event log the single source of truth for state derivation.

The test uses an in-memory ``FakeSqlExecutor`` that records every
``execute_sql`` call and returns canned rows so the use case can be
asserted without a live database. The pattern mirrors the adapter test
in ``tests/test_lifecycle_slice.py::test_lifecycle_insforge_adapter_implements_lifecycle_port``.
"""
from __future__ import annotations

import pytest


class _FakeSqlExecutor:
    """Stub executor that records calls and returns canned rows.

    The close use case is event-sourced — every active placement
    produces one INSERT into ``animal_lifecycle_events`` with the
    closing event type. The fake returns zero rows from the SELECT
    that lists active placements when the test says so; the test
    asserts ``calls`` against the expected INSERT sequences.

    The fake also handles ``INSERT ... RETURNING id`` — it returns
    a row with a stable synthetic id so the use case can thread
    the new id into the closing events as ``caused_by_event_id``.
    """

    def __init__(
        self,
        active_intakes: list[dict[str, object]] | None = None,
        active_fosters: list[dict[str, object]] | None = None,
        active_adoptions: list[dict[str, object]] | None = None,
        death_event_id: str = "death-event-uuid-1",
    ) -> None:
        self.calls: list[tuple[str, list]] = []
        self._responses: dict[str, list[dict[str, object]]] = {
            "FROM entradas": list(active_intakes or []),
            "FROM acogidas": list(active_fosters or []),
            "FROM adopciones": list(active_adoptions or []),
        }
        self._death_event_id = death_event_id
        self._returning_id_counter = 0

    def execute_sql(
        self, query: str, params: list | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        # ``INSERT ... RETURNING id`` for the death event — return a
        # stable synthetic id so the closing events can reference it.
        if "INSERT INTO animal_lifecycle_events" in query and "RETURNING id" in query:
            self._returning_id_counter += 1
            return [{"id": f"{self._death_event_id}-#{self._returning_id_counter}"}]
        for marker, rows in self._responses.items():
            if marker in query:
                return rows
        return []


def _closing_event_types(calls: list[tuple[str, list]]) -> list[str]:
    """Return the ``event_type`` argument from every INSERT into
    ``animal_lifecycle_events``."""
    out: list[str] = []
    for sql, params in calls:
        if "INSERT INTO animal_lifecycle_events" in sql and len(params) >= 2:
            out.append(str(params[1]))
    return out


def test_close_all_on_death_with_no_active_records_emits_only_death() -> None:
    """Happy edge: no active placements → exactly 1 event (DEATH_RECORDED).

    The cascade re-derives state after every event insert (PR-A's
    cascade contract), so emitting only ``DEATH_RECORDED`` is the
    minimum viable output when there is nothing to close.
    """
    from app.modules.lifecycle.application.close_all_on_death import (
        close_all_on_death,
    )

    executor = _FakeSqlExecutor()
    close_all_on_death(
        executor, animal_id="animal-uuid-1", event_timestamp="2026-08-01T00:00:00Z"
    )
    events = _closing_event_types(executor.calls)
    assert events == ["DEATH_RECORDED"], (
        f"expected exactly one DEATH_RECORDED event, got {events}"
    )


def test_close_all_on_death_with_one_intake_emits_two_events() -> None:
    """Death with 1 active intake → 2 events (DEATH + intake close)."""
    from app.modules.lifecycle.application.close_all_on_death import (
        close_all_on_death,
    )

    executor = _FakeSqlExecutor(
        active_intakes=[{"IDEntrada": "intake-uuid-1", "FSalida": None}],
    )
    close_all_on_death(
        executor, animal_id="animal-uuid-2", event_timestamp="2026-08-01T00:00:00Z"
    )
    events = _closing_event_types(executor.calls)
    assert "DEATH_RECORDED" in events, "DEATH_RECORDED must be emitted"
    assert "INTAKE_CLOSED_BY_DEATH" in events, (
        "one active intake must produce an INTAKE_CLOSED_BY_DEATH event"
    )
    assert len(events) == 2, (
        f"expected DEATH + 1 intake close = 2 events, got {events}"
    )


def test_close_all_on_death_with_intake_foster_adoption_emits_four() -> None:
    """Death with 1 active of each placement → 4 events (death + 3 closes)."""
    from app.modules.lifecycle.application.close_all_on_death import (
        close_all_on_death,
    )

    executor = _FakeSqlExecutor(
        active_intakes=[{"IDEntrada": "intake-uuid-1", "FSalida": None}],
        active_fosters=[{"IDAcogida": "foster-uuid-1", "FFinal": None}],
        active_adoptions=[{"IDAdopcion": "adoption-uuid-1", "FDevolucion": None}],
    )
    close_all_on_death(
        executor, animal_id="animal-uuid-3", event_timestamp="2026-08-01T00:00:00Z"
    )
    events = _closing_event_types(executor.calls)
    assert "DEATH_RECORDED" in events
    assert "INTAKE_CLOSED_BY_DEATH" in events
    assert "FOSTER_CLOSED_BY_DEATH" in events
    assert "ADOPTION_CLOSED_BY_DEATH" in events
    assert len(events) == 4, f"expected 4 events, got {events}"


def test_close_all_on_death_never_updates_source_tables() -> None:
    """Source-of-truth invariant: closing must be event-sourced.

    The append-only trigger on ``animal_lifecycle_events`` is what makes
    the event log the single source of truth for state derivation.
    UPDATE/DELETE on ``entradas`` / ``acogidas`` / ``adopciones`` would
    create a second source — explicitly forbidden by the spec.
    """
    from app.modules.lifecycle.application.close_all_on_death import (
        close_all_on_death,
    )

    executor = _FakeSqlExecutor(
        active_intakes=[{"IDEntrada": "intake-uuid-1", "FSalida": None}],
        active_fosters=[{"IDAcogida": "foster-uuid-1", "FFinal": None}],
        active_adoptions=[{"IDAdopcion": "adoption-uuid-1", "FDevolucion": None}],
    )
    close_all_on_death(
        executor, animal_id="animal-uuid-4", event_timestamp="2026-08-01T00:00:00Z"
    )
    for sql, _params in executor.calls:
        normalized = sql.strip().upper()
        assert not normalized.startswith("UPDATE"), (
            f"close_all_on_death must not UPDATE source tables; got: {sql!r}"
        )
        assert not normalized.startswith("DELETE"), (
            f"close_all_on_death must not DELETE source tables; got: {sql!r}"
        )


def test_close_all_on_death_attaches_death_event_id_as_caused_by() -> None:
    """Every closing event references the DEATH_RECORDED event id so the
    audit trail is traceable end-to-end.

    The death event's ``caused_by_event_id`` is ``NULL`` (no prior
    event — the death IS the trigger). The use case captures the
    ``RETURNING id`` from the death INSERT and threads it into the
    closing events' ``caused_by_event_id`` so the lineage is
    queryable end-to-end.
    """
    from app.modules.lifecycle.application.close_all_on_death import (
        close_all_on_death,
    )

    executor = _FakeSqlExecutor(
        active_intakes=[{"IDEntrada": "intake-uuid-1", "FSalida": None}],
        death_event_id="death-event-uuid-test",
    )
    close_all_on_death(
        executor, animal_id="animal-uuid-5", event_timestamp="2026-08-01T00:00:00Z"
    )
    inserts = [
        (sql, params)
        for sql, params in executor.calls
        if "INSERT INTO animal_lifecycle_events" in sql
    ]
    assert len(inserts) == 2, f"expected 2 inserts, got {len(inserts)}"
    death_call_params = inserts[0][1]
    close_call_params = inserts[1][1]
    # The death event has caused_by_event_id NULL (it is the trigger).
    assert death_call_params[3] is None, (
        f"DEATH_RECORDED caused_by_event_id must be NULL; "
        f"got {death_call_params[3]!r}"
    )
    # The closing event's caused_by_event_id references the death
    # event id returned by the RETURNING clause.
    assert close_call_params[3] == "death-event-uuid-test-#1", (
        f"closing event caused_by_event_id ({close_call_params[3]!r}) "
        f"must reference the DEATH_RECORDED event id from RETURNING"
    )


def test_close_all_on_death_passes_animal_id_to_every_insert() -> None:
    """All inserts bind the same animal_id so the event log stays grouped."""
    from app.modules.lifecycle.application.close_all_on_death import (
        close_all_on_death,
    )

    executor = _FakeSqlExecutor(
        active_intakes=[{"IDEntrada": "intake-uuid-1", "FSalida": None}],
    )
    close_all_on_death(
        executor, animal_id="animal-uuid-6", event_timestamp="2026-08-01T00:00:00Z"
    )
    inserts = [
        params
        for sql, params in executor.calls
        if "INSERT INTO animal_lifecycle_events" in sql
    ]
    animal_ids = {params[0] for params in inserts}
    assert animal_ids == {"animal-uuid-6"}, (
        f"all inserts must bind animal-uuid-6; got {animal_ids}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
