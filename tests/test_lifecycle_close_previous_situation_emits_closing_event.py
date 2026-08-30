"""Use-case tests for ``close_previous_situation`` (LIFECYCLE-03 PR-C).

The use case is event-sourced (AGENTS.md §22, §33.4): it emits a
single ``INSERT INTO animal_lifecycle_events`` row for the closing
event, and never issues ``UPDATE`` against ``entradas`` / ``acogidas``
/ ``adopciones``. The closing event references the trigger event via
``caused_by_event_id`` so the lineage is queryable end-to-end.

The test uses an in-memory ``FakeSqlExecutor`` that records every
``execute_sql`` call so the use case can be asserted without a live
database. The pattern mirrors ``tests/test_lifecycle_close_all_on_death_*
.py`` and ``tests/test_lifecycle_can_delete_animal_blocks_on_sanidad.py``.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.modules.lifecycle.application.close_previous_situation import (
    CLOSING_EVENT_BY_CATEGORY,
    DEFAULT_CREATED_BY,
    UnknownSituationCategoryError,
    close_previous_situation,
)
from app.modules.lifecycle.domain.animal_state import DerivationKind, DerivationResult


class _FakeSqlExecutor:
    """Stub executor that records every ``execute_sql`` call.

    Returns an empty row list from every call so the use case takes
    the "happy path" branch when given a recognised category. Tests
    assert against ``calls`` for the INSERT shape and parameter list.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []

    def execute_sql(
        self, query: str, params: list | None = None
    ) -> list[dict[str, object]]:
        self.calls.append((query, list(params or [])))
        return []


def _insert_params(calls: list[tuple[str, list]]) -> list[list]:
    """Return the parameter list from every closing-event INSERT."""
    return [
        params
        for sql, params in calls
        if "INSERT INTO animal_lifecycle_events" in sql
    ]


def test_close_previous_situation_emits_intake_closing_event() -> None:
    """INTAKE -> INTAKE_CLOSED_BY_FOSTER, ``source_entity_type``/``id`` passed through."""
    executor = _FakeSqlExecutor()
    close_previous_situation(
        executor,
        animal_id="animal-uuid-1",
        category="INTAKE",
        caused_by_event_id="trigger-event-uuid-1",
        event_timestamp="2026-08-01T00:00:00Z",
        source_entity_type="entradas",
        source_entity_id="entrada-uuid-1",
        created_by="tester",
    )
    inserts = _insert_params(executor.calls)
    assert len(inserts) == 1, f"expected one INSERT, got {len(inserts)}"
    params = inserts[0]
    assert params[0] == "animal-uuid-1"
    assert params[1] == "INTAKE_CLOSED_BY_FOSTER"
    assert params[2] == "2026-08-01T00:00:00Z"
    assert params[3] == "trigger-event-uuid-1"
    assert params[4] == "entradas"
    assert params[5] == "entrada-uuid-1"
    assert params[6] == "tester"


def test_close_previous_situation_emits_foster_closing_event() -> None:
    """FOSTER -> FOSTER_CLOSED_BY_ADOPTION."""
    executor = _FakeSqlExecutor()
    close_previous_situation(
        executor,
        animal_id="animal-uuid-2",
        category="FOSTER",
        caused_by_event_id="trigger-event-uuid-2",
        event_timestamp="2026-08-02T00:00:00Z",
        source_entity_type="acogidas",
        source_entity_id="acogida-uuid-2",
    )
    inserts = _insert_params(executor.calls)
    assert inserts[0][1] == "FOSTER_CLOSED_BY_ADOPTION"
    assert inserts[0][4] == "acogidas"


def test_close_previous_situation_emits_adoption_returned() -> None:
    """ADOPTION -> ADOPTION_RETURNED (Adoptado -> return-to-foster)."""
    executor = _FakeSqlExecutor()
    close_previous_situation(
        executor,
        animal_id="animal-uuid-3",
        category="ADOPTION",
        caused_by_event_id="trigger-event-uuid-3",
        event_timestamp="2026-08-03T00:00:00Z",
        source_entity_type="adopciones",
        source_entity_id="adopcion-uuid-3",
    )
    inserts = _insert_params(executor.calls)
    assert inserts[0][1] == "ADOPTION_RETURNED"
    assert inserts[0][4] == "adopciones"


def test_close_previous_situation_raises_for_unknown_category() -> None:
    """Unknown category raises ``UnknownSituationCategoryError`` and emits no event.

    The set of categories is closed (AGENTS.md §4); a typo or a
    future situation category that has no matching closing event must
    surface as a domain error rather than silently emit the wrong
    event type.
    """
    executor = _FakeSqlExecutor()
    with pytest.raises(UnknownSituationCategoryError) as excinfo:
        close_previous_situation(
            executor,
            animal_id="animal-uuid-4",
            category="UNKNOWN",
            caused_by_event_id="trigger-event-uuid-4",
            event_timestamp="2026-08-04T00:00:00Z",
        )
    assert excinfo.value.category == "UNKNOWN"
    assert "UNKNOWN" in str(excinfo.value)
    assert executor.calls == [], "no INSERT must be emitted for an unknown category"


def test_close_previous_situation_unknown_category_error_carries_category() -> None:
    """The error carries the rejected category on ``.category`` so callers can log it.

    Distinct from the smoke test above — pins the structured attribute
    that downstream observability depends on.
    """
    err = UnknownSituationCategoryError("INVALID")
    assert err.category == "INVALID"
    assert "INVALID" in str(err)


def test_close_previous_situation_coerces_datetime_to_isoformat() -> None:
    """``event_timestamp`` accepts ``datetime`` and serialises via ``.isoformat()``.

    The use case signature is ``str | datetime`` so callers can pass
    a parsed DB timestamp without a manual conversion.
    """
    executor = _FakeSqlExecutor()
    close_previous_situation(
        executor,
        animal_id="animal-uuid-5",
        category="INTAKE",
        caused_by_event_id="trigger-event-uuid-5",
        event_timestamp=datetime(2026, 8, 5, 12, 30, 0),
    )
    inserts = _insert_params(executor.calls)
    assert inserts[0][2] == "2026-08-05T12:30:00", (
        f"datetime must be serialised via isoformat; got {inserts[0][2]!r}"
    )


def test_close_previous_situation_source_entity_optional() -> None:
    """``source_entity_type``/``source_entity_id`` may be omitted.

    The source-entity link is optional; when omitted the closing event
    has no audit-trail anchor to a specific source row, but the event
    itself is still emitted.
    """
    executor = _FakeSqlExecutor()
    close_previous_situation(
        executor,
        animal_id="animal-uuid-6",
        category="FOSTER",
        caused_by_event_id="trigger-event-uuid-6",
        event_timestamp="2026-08-06T00:00:00Z",
    )
    inserts = _insert_params(executor.calls)
    assert inserts[0][4] is None
    assert inserts[0][5] is None


def test_close_previous_situation_uses_default_created_by() -> None:
    """When the caller omits ``created_by`` the audit-trail actor is the default."""
    executor = _FakeSqlExecutor()
    close_previous_situation(
        executor,
        animal_id="animal-uuid-7",
        category="INTAKE",
        caused_by_event_id="trigger-event-uuid-7",
        event_timestamp="2026-08-07T00:00:00Z",
    )
    inserts = _insert_params(executor.calls)
    assert inserts[0][6] == DEFAULT_CREATED_BY


def test_close_previous_situation_never_updates_source_tables() -> None:
    """Source-of-truth invariant: the closing is event-sourced, never UPDATE.

    Mirrors ``test_lifecycle_close_all_on_death_never_updates_source_tables``
    — the lifecycle use cases are append-only by design (the
    ``animal_lifecycle_events`` trigger enforces the event log as the
    single source of truth for state derivation; updating the source
    rows would create a second, divergent source).
    """
    executor = _FakeSqlExecutor()
    close_previous_situation(
        executor,
        animal_id="animal-uuid-8",
        category="ADOPTION",
        caused_by_event_id="trigger-event-uuid-8",
        event_timestamp="2026-08-08T00:00:00Z",
    )
    for sql, _params in executor.calls:
        normalized = sql.strip().upper()
        assert not normalized.startswith("UPDATE"), (
            f"close_previous_situation must not UPDATE source tables; got: {sql!r}"
        )
        assert not normalized.startswith("DELETE"), (
            f"close_previous_situation must not DELETE source tables; got: {sql!r}"
        )


def test_closing_event_by_category_is_closed_set() -> None:
    """The category -> closing-event map is the closed source of truth (§4).

    Mirrors the helper in ``can_delete_animal`` — the set of categories
    is the set of closing events. Adding a new transition means both
    adding a member here AND extending the ``animal_lifecycle_events``
    CHECK enum at ``app/core/domain_lifecycle.py:69-76``.
    """
    assert CLOSING_EVENT_BY_CATEGORY == {
        "INTAKE": "INTAKE_CLOSED_BY_FOSTER",
        "FOSTER": "FOSTER_CLOSED_BY_ADOPTION",
        "ADOPTION": "ADOPTION_RETURNED",
    }

    # -------------------------------------------------------------------
    # PR-C state-update tests — lifecycle_port chaining.
    # -------------------------------------------------------------------

class _StubLifecyclePort:
    """Stub for LifecyclePort that records every call."""

    def __init__(
        self,
        next_result=None,
    ):
        self.next_result = next_result or DerivationResult(
            state="Acogida",
            kind=DerivationKind.ACOGIDA,
        )
        self.calls = []

    def calculate_state(self, animal_id):
        self.calls.append((animal_id, None))
        return self.next_result

    def persist_animal_state(self, animal_id, result):
        self.calls.append((animal_id, result))

def test_close_previous_situation_calls_lifecycle_port_after_emitting_event():
    """PR-C: when lifecycle_port is supplied, calculate + persist after closing event."""
    executor = _FakeSqlExecutor()
    lifecycle_port = _StubLifecyclePort()

    close_previous_situation(
        executor,
        animal_id="animal-transition-99",
        category="INTAKE",
        caused_by_event_id="trigger-ev-99",
        event_timestamp="2026-08-01T00:00:00Z",
        lifecycle_port=lifecycle_port,
    )

    assert len(lifecycle_port.calls) == 2
    calc_call, persist_call = lifecycle_port.calls
    assert calc_call == ("animal-transition-99", None)
    assert persist_call[0] == "animal-transition-99"
    assert persist_call[1] is lifecycle_port.next_result

def test_close_previous_situation_no_state_update_when_port_is_none():
    """PR-C: lifecycle_port=None emits closing event without updating state."""
    executor = _FakeSqlExecutor()

    close_previous_situation(
        executor,
        animal_id="animal-no-port-2",
        category="FOSTER",
        caused_by_event_id="trigger-ev-2",
        event_timestamp="2026-08-01T00:00:00Z",
    )
    inserts = _insert_params(executor.calls)
    assert len(inserts) == 1
    assert inserts[0][1] == "FOSTER_CLOSED_BY_ADOPTION"

    if __name__ == "__main__":
        pytest.main([__file__, "-v"])
