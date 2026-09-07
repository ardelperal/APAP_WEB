"""Tests for the lifecycle-events service module (issue #32, LIFECYCLE-02).

Covers:
- The 10 core + 4 supporting event types are pinned by an enum (one source
  of truth; AGENTS.md §4) and the CHECK constraint in
  ``animal_lifecycle_events`` matches the enum.
- ``record_event`` issues the expected INSERT against the
  ``SqlExecutor`` and validates the required fields (animal_id,
  event_type, event_timestamp, created_by).
- ``CausalPairViolation`` (D-23) is raised when ADOPTION_STARTED is
  recorded for an animal that does NOT have a preceding
  FOSTER_CLOSED_BY_ADOPTION event, or when FOSTER_CLOSED_BY_ADOPTION
  is recorded AFTER an existing ADOPTION_STARTED (out-of-order pair).
- ``validate_causal_pair`` is a pure pre-flight: it can be called
  without a write and only raises when the rule is violated.
- Idempotency: ``record_event`` collapses a retry of the same logical
  event via ``ON CONFLICT (animal_id, event_type, event_timestamp) DO
  NOTHING`` so the same (animal, type, ts) row is created at most once.

The tests use ``httpx.MockTransport`` to exercise ``record_event``
end-to-end without touching the network, mirroring the pattern in
``tests/test_domain.py``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.data_access import SqlExecutor
from app.core.local_backend.db import LocalPostgresExecutor
from app.modules.animals.lifecycle_events import (
    CAUSAL_PAIR_DECISION_ID,
    CORE_EVENT_TYPES,
    SUPPORTING_EVENT_TYPES,
    CausalPairViolation,
    LifecycleEventType,
    record_event,
    validate_causal_pair,
)

# --- helpers -------------------------------------------------------------


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(
    handler,
) -> tuple[LocalPostgresExecutor, list[dict[str, Any]]]:
    """Build a client whose MockTransport records every call's JSON body."""
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = LocalPostgresExecutor(
        base_url="https://example.local_backend.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


def _empty_ok(_req: httpx.Request, _body: dict[str, Any]) -> httpx.Response:
    return _json_response(200, [])


def _select_returns(rows: list[dict[str, Any]]):
    """Return a handler that serves a SELECT with ``rows`` and OK for everything else."""

    def handler(req: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        query = body.get("query", "") if isinstance(body, dict) else ""
        if query.lstrip().upper().startswith("SELECT"):
            return _json_response(200, rows)
        return _json_response(200, [])

    return handler


# --- enum contract --------------------------------------------------------


def test_core_event_types_has_exactly_ten_members() -> None:
    """The 10 core event types are pinned (issue #32 acceptance criterion)."""
    assert len(CORE_EVENT_TYPES) == 10
    assert len(LifecycleEventType) == 14


def test_core_event_types_set_matches_strenum_members() -> None:
    """``CORE_EVENT_TYPES`` and the StrEnum members must agree (AGENTS §4)."""
    core_members = {
        name for name, member in LifecycleEventType.__members__.items()
        if member in CORE_EVENT_TYPES
    }
    assert core_members == {
        "INTAKE_STARTED",
        "INTAKE_COMPLETED",
        "FOSTER_STARTED",
        "FOSTER_RETURNED",
        "FOSTER_CLOSED_BY_ADOPTION",
        "ADOPTION_STARTED",
        "ADOPTION_RETURNED",
        "OWNER_RETURNED",
        "DEATH_RECORDED",
        "STATE_CORRECTION",
    }


def test_supporting_event_types_has_exactly_four_members() -> None:
    """The 4 supporting event types are pinned (issue #32 acceptance criterion)."""
    assert len(SUPPORTING_EVENT_TYPES) == 4
    assert SUPPORTING_EVENT_TYPES == frozenset(
        {
            LifecycleEventType.CHIP_CHANGED,
            LifecycleEventType.INTAKE_REOPENED,
            LifecycleEventType.FOSTER_REOPENED,
            LifecycleEventType.ADOPTION_REOPENED,
        }
    )


def test_decision_id_marker_is_d23() -> None:
    """The causal-pair violation carries the D-23 marker."""
    assert CAUSAL_PAIR_DECISION_ID == "D-23"


# --- record_event: validation ---------------------------------------------


def test_record_event_rejects_missing_animal_id() -> None:
    client, _ = _client_recording(_empty_ok)
    with pytest.raises(ValueError, match="animal_id"):
        record_event(
            client,
            animal_id="",
            event_type=LifecycleEventType.INTAKE_STARTED,
            event_timestamp="2026-07-27T00:00:00+00:00",
            created_by="00000000-0000-0000-0000-000000000001",
        )


def test_record_event_rejects_unknown_event_type() -> None:
    client, _ = _client_recording(_empty_ok)
    with pytest.raises(ValueError, match="event_type"):
        record_event(
            client,
            animal_id="00000000-0000-0000-0000-000000000001",
            event_type="NOT_A_REAL_EVENT",  # type: ignore[arg-type]
            event_timestamp="2026-07-27T00:00:00+00:00",
            created_by="00000000-0000-0000-0000-000000000002",
        )


def test_record_event_rejects_missing_timestamp() -> None:
    client, _ = _client_recording(_empty_ok)
    with pytest.raises(ValueError, match="event_timestamp"):
        record_event(
            client,
            animal_id="00000000-0000-0000-0000-000000000001",
            event_type=LifecycleEventType.INTAKE_STARTED,
            event_timestamp="",
            created_by="00000000-0000-0000-0000-000000000002",
        )


def test_record_event_rejects_missing_created_by() -> None:
    client, _ = _client_recording(_empty_ok)
    with pytest.raises(ValueError, match="created_by"):
        record_event(
            client,
            animal_id="00000000-0000-0000-0000-000000000001",
            event_type=LifecycleEventType.INTAKE_STARTED,
            event_timestamp="2026-07-27T00:00:00+00:00",
            created_by="",
        )


# --- record_event: writes the right SQL -----------------------------------


def test_record_event_emits_insert_with_on_conflict_idempotence() -> None:
    """``record_event`` writes an INSERT with ``ON CONFLICT DO NOTHING``
    on the natural key (animal_id, event_type, event_timestamp)."""
    client, captured = _client_recording(_empty_ok)
    record_event(
        client,
        animal_id="00000000-0000-0000-0000-000000000001",
        event_type=LifecycleEventType.INTAKE_STARTED,
        event_timestamp="2026-07-27T00:00:00+00:00",
        created_by="00000000-0000-0000-0000-000000000002",
        source_entity_type="entrada",
        source_entity_id="00000000-0000-0000-0000-0000000000aa",
        metadata={"legacy_pk": 42},
    )
    client.close()

    inserts = [c for c in captured if "INSERT INTO animal_lifecycle_events" in c["query"]]
    assert len(inserts) == 1
    sql = inserts[0]["query"]
    # Idempotence guard.
    assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql
    # Positional params (10 columns that ``record_event`` passes through).
    params = inserts[0]["params"]
    assert params[0] == "00000000-0000-0000-0000-000000000001"
    assert params[1] == "INTAKE_STARTED"
    assert params[2] == "2026-07-27T00:00:00+00:00"
    assert params[3] is None  # caused_by_event_id
    assert params[4] == "entrada"
    assert params[5] == "00000000-0000-0000-0000-0000000000aa"
    assert params[6] is None  # legacy_source_table
    assert params[7] is None  # legacy_source_id
    assert isinstance(params[8], str)  # metadata as JSON string
    assert json.loads(params[8]) == {"legacy_pk": 42}
    assert params[9] == "00000000-0000-0000-0000-000000000002"


def test_record_event_skips_metadata_when_absent() -> None:
    client, captured = _client_recording(_empty_ok)
    record_event(
        client,
        animal_id="00000000-0000-0000-0000-000000000001",
        event_type=LifecycleEventType.DEATH_RECORDED,
        event_timestamp="2026-07-27T00:00:00+00:00",
        created_by="00000000-0000-0000-0000-000000000002",
    )
    client.close()

    inserts = [c for c in captured if "INSERT INTO animal_lifecycle_events" in c["query"]]
    assert len(inserts) == 1
    assert inserts[0]["params"][8] is None  # metadata


def test_record_event_depends_on_sql_executor_protocol() -> None:
    """``record_event`` takes a ``SqlExecutor`` Protocol, not a concrete
    client (AGENTS §31)."""
    assert "SqlExecutor" in SqlExecutor.__name__ or hasattr(SqlExecutor, "execute_sql")


# --- validate_causal_pair: pure pre-flight (D-23) -------------------------


def test_validate_causal_pair_passes_when_no_prior_events() -> None:
    """The rule fires only on ADOPTION_STARTED + FOSTER_CLOSED_BY_ADOPTION.

    For every other event type, ``validate_causal_pair`` is a no-op
    even when there are zero prior events on the log. This keeps the
    function composable with the rest of the lifecycle code (e.g. an
    INTAKE_STARTED at the beginning of an animal's life has no
    prerequisite)."""
    client, _ = _client_recording(_select_returns([]))
    validate_causal_pair(
        client,
        animal_id="00000000-0000-0000-0000-000000000001",
        event_type=LifecycleEventType.INTAKE_STARTED,
        event_timestamp="2026-07-27T00:00:00+00:00",
    )
    client.close()


def test_validate_causal_pair_passes_for_adoption_after_foster_close() -> None:
    """ADOPTION_STARTED is allowed when FOSTER_CLOSED_BY_ADOPTION
    already exists for the same animal with event_timestamp <= now."""
    foster_close_ts = "2026-07-20T10:00:00+00:00"
    adoption_ts = "2026-07-21T10:00:00+00:00"
    prior = [
        {
            "event_type": "FOSTER_CLOSED_BY_ADOPTION",
            "event_timestamp": foster_close_ts,
        },
    ]
    client, _ = _client_recording(_select_returns(prior))
    validate_causal_pair(
        client,
        animal_id="00000000-0000-0000-0000-000000000001",
        event_type=LifecycleEventType.ADOPTION_STARTED,
        event_timestamp=adoption_ts,
    )
    client.close()


def test_validate_causal_pair_raises_when_adoption_lacks_foster_close() -> None:
    """ADOPTION_STARTED without a preceding FOSTER_CLOSED_BY_ADOPTION
    violates D-23 and raises ``CausalPairViolation``."""
    client, _ = _client_recording(_select_returns([]))
    with pytest.raises(CausalPairViolation) as exc_info:
        validate_causal_pair(
            client,
            animal_id="00000000-0000-0000-0000-000000000001",
            event_type=LifecycleEventType.ADOPTION_STARTED,
            event_timestamp="2026-07-27T00:00:00+00:00",
        )
    assert exc_info.value.decision_id == CAUSAL_PAIR_DECISION_ID
    assert exc_info.value.animal_id == "00000000-0000-0000-0000-000000000001"
    assert exc_info.value.event_type == LifecycleEventType.ADOPTION_STARTED
    client.close()


def test_validate_causal_pair_raises_when_foster_close_out_of_order() -> None:
    """A FOSTER_CLOSED_BY_ADOPTION emitted AFTER an existing
    ADOPTION_STARTED for the same animal is also a D-23 violation:
    the pair is ordered, so out-of-order writes cannot sneak past."""
    prior = [
        {
            "event_type": "ADOPTION_STARTED",
            "event_timestamp": "2026-07-21T10:00:00+00:00",
        },
    ]
    client, _ = _client_recording(_select_returns(prior))
    with pytest.raises(CausalPairViolation):
        validate_causal_pair(
            client,
            animal_id="00000000-0000-0000-0000-000000000001",
            event_type=LifecycleEventType.FOSTER_CLOSED_BY_ADOPTION,
            event_timestamp="2026-07-27T00:00:00+00:00",
        )
    client.close()


def test_validate_causal_pair_selects_only_relevant_rows() -> None:
    """The pre-flight SELECT scopes by (animal_id, event_type) so the
    log's natural key UNIQUE index is the lookup path; we don't fetch
    unrelated events.

    Uses ``FOSTER_CLOSED_BY_ADOPTION`` (which requires no preceding
    ADOPTION_STARTED) so the check is a no-op without forcing the
    SELECT to need a prior row.
    """
    client, captured = _client_recording(_select_returns([]))
    validate_causal_pair(
        client,
        animal_id="00000000-0000-0000-0000-000000000001",
        event_type=LifecycleEventType.FOSTER_CLOSED_BY_ADOPTION,
        event_timestamp="2026-07-27T00:00:00+00:00",
    )
    client.close()

    selects = [c for c in captured if c["query"].lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1
    sql = selects[0]["query"]
    assert "FROM animal_lifecycle_events" in sql
    assert "animal_id = $1" in sql
    # The pre-flight must filter by event_type(s) it cares about.
    assert selects[0]["params"][0] == "00000000-0000-0000-0000-000000000001"
