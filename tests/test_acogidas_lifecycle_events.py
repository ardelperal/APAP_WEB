"""Lifecycle-event emission tests for ``app.modules.acogidas.service``.

LIFECYCLE-02 (issue #32): every foster-stay transition in the
``acogidas`` slice MUST emit the matching event into
``animal_lifecycle_events`` so the event log is the single source of
truth for state derivation. The use case under test lives in
``app.modules.acogidas.service`` — the routes stay pure HTTP glue.

What these tests pin
--------------------

``create_acogida`` writes three rows into ``animal_lifecycle_events``
inside the same DB transaction as the ``acogidas`` INSERT:

  1. ``FOSTER_STARTED`` — the entry into the foster stay.
  2. ``INTAKE_CLOSED_BY_FOSTER`` — emitted by
     ``close_previous_situation(category="INTAKE")`` to record the
     Albergue -> Acogida transition (the previous intake situation is
     closed event-sourced, not via an ``entradas`` UPDATE).
  3. ``actualizar_estado_animal`` is called twice (once inside
     ``record_event`` and once explicitly after the closing event) so the
     ``animal_current_state`` cache row reflects the new ``Acogida``
     state.

``close_acogida`` writes one row into ``animal_lifecycle_events``:

  1. ``FOSTER_RETURNED`` — the exit out of the foster stay.
  2. ``actualizar_estado_animal`` is called twice (same pattern as
     above) so the cache row reverts to ``Albergue`` / ``Pendiente`` /
     etc. depending on the other active placements.

Test pattern
------------

A ``FakeSqlExecutor`` records every ``execute_sql`` call so the
service layer can be exercised without a live database. The pattern
mirrors the one in
``tests/test_lifecycle_close_previous_situation_emits_closing_event.py``
and ``tests/test_lifecycle_close_all_on_death_emits_closing_events.py``
— those are the canonical references for this executor shape in the
lifecycle slice.

Scope
------

This file is scoped to the service-layer event emission. The route
layer already pins the SQL shape via ``_feed_handler`` in
``tests/test_acogidas_routes.py``; the ``acogidas`` queries are covered
by ``tests/test_acogidas_queries.py``. Here we focus on the new
lifecycle contract that LIFECYCLE-02 adds on top of the existing CRUD.
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.acogidas import service as acogidas_service
from app.modules.animals.lifecycle_events import LifecycleEventType
from app.modules.lifecycle.application.close_previous_situation import (
    CLOSING_EVENT_BY_CATEGORY,
)

# --- helpers --------------------------------------------------------------


ACOGIDA_UUID = "22222222-2222-2222-2222-222222222222"
ANIMAL_UUID = "11111111-1111-1111-1111-111111111111"


class FakeSqlExecutor:
    """Stub executor that records every ``execute_sql`` call.

    The executor handles every SQL shape that the ``acogidas`` service
    is expected to issue under the lifecycle-aware code path:

      * FK validation SELECTs (animales / casas_acogida / voluntarios /
        entradas) — each returns a "valid active row" so the validation
        chain passes.
      * ``INSERT INTO acogidas`` and ``UPDATE acogidas SET ...`` —
        returns the canned row so the service can map it back to an
        :class:`Acogida`.
      * Every other call (lifecycle events INSERT, cache UPSERT, the
        cascade's ficha + active-placements SELECTs) returns an empty
        row list, which the cascade treats as "no other active
        placements".

    Mirrors the same pattern as
    ``tests/test_lifecycle_close_previous_situation_emits_closing_event.py``
    and ``tests/test_lifecycle_close_all_on_death_emits_closing_events.py``.
    """

    def __init__(
        self,
        insert_row: dict[str, Any] | None = None,
        update_row: dict[str, Any] | None = None,
    ) -> None:
        self.calls: list[tuple[str, list[Any]]] = []
        self._insert_row = insert_row
        self._update_row = update_row

    def execute_sql(
        self, query: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        normalized = query.strip()
        params_list = list(params or [])
        self.calls.append((normalized, params_list))

        # FK validation SELECTs — the service layer checks each
        # referenced id is active before issuing the INSERT / UPDATE.
        # Returning a valid active row makes the happy path pass.
        if normalized.startswith("SELECT id, activo FROM animales"):
            return [{"id": params_list[0], "activo": True}]
        if normalized.startswith("SELECT id, activo FROM casas_acogida"):
            return [{"id": params_list[0], "activo": True}]
        if (
            normalized.startswith("SELECT id, activo FROM voluntarios")
            and "activo = true" in normalized
        ):
            return [{"id": params_list[0], "activo": True}]
        if normalized.startswith("SELECT id FROM entradas"):
            return [{"id": params_list[0]}]

        if "INSERT INTO acogidas" in normalized:
            return [self._insert_row or _default_insert_row()]
        if "UPDATE acogidas" in normalized and "fecha_final" in normalized:
            return [self._update_row or _default_update_row()]
        return []


def _default_insert_row() -> dict[str, Any]:
    """Canonical returned row for the ``INSERT INTO acogidas`` mock."""
    return {
        "id": ACOGIDA_UUID,
        "animal_id": ANIMAL_UUID,
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "fecha_baja": None,
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }


def _default_update_row() -> dict[str, Any]:
    """Canonical returned row for the ``UPDATE acogidas SET fecha_final`` mock."""
    from datetime import date

    return {
        **_default_insert_row(),
        "fecha_final": str(date.today()),
        "activo": True,
    }


def _params_minimal() -> dict[str, Any]:
    """Minimal valid params dict for ``create_acogida``."""
    return {
        "animal_id": ANIMAL_UUID,
        "casa_acogida_id": None,
        "voluntario_acogida_id": None,
        "voluntario_seguimiento1_id": None,
        "voluntario_seguimiento2_id": None,
        "voluntario_sanitario_id": None,
        "fecha_inicio": "2026-07-04",
        "fecha_final": None,
        "entrada_origen_id": None,
        "direccion": "Calle Mayor 12, Alcalá de Henares",
        "telefono": "600123456",
        "observaciones": "Animal tranquilo, sin medicación",
    }


def _lifecycle_event_inserts(
    calls: list[tuple[str, list[Any]]],
) -> list[tuple[str, list[Any]]]:
    """Return the parameter lists from every ``animal_lifecycle_events`` INSERT."""
    return [
        (sql, params)
        for sql, params in calls
        if "INSERT INTO animal_lifecycle_events" in sql
    ]


def _animal_current_state_inserts(
    calls: list[tuple[str, list[Any]]],
) -> list[tuple[str, list[Any]]]:
    """Return the parameter lists from every ``animal_current_state`` UPSERT."""
    return [
        (sql, params)
        for sql, params in calls
        if "INSERT INTO animal_current_state" in sql
    ]


# --- create_acogida: lifecycle event emission -----------------------------


def test_create_acogida_emits_foster_started_event() -> None:
    """``create_acogida`` writes a ``FOSTER_STARTED`` event into the log.

    The event MUST be emitted via the canonical
    ``record_event(...)`` use case so the ``ON CONFLICT (animal_id,
    event_type, event_timestamp) DO NOTHING`` idempotence guard applies
    (issue #32 acceptance). The closing event from
    ``close_previous_situation`` is a separate INSERT — that one is
    pinned in a sibling test.
    """
    executor = FakeSqlExecutor()

    result = acogidas_service.create_acogida(executor, _params_minimal())

    assert isinstance(result, acogidas_service.Acogida)

    inserts = _lifecycle_event_inserts(executor.calls)
    foster_started = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2 and params[1] == "FOSTER_STARTED"
    ]
    assert len(foster_started) == 1, (
        f"create_acogida MUST emit exactly one FOSTER_STARTED event; "
        f"got {len(foster_started)} matching INSERTs across "
        f"{len(inserts)} lifecycle-event INSERTs"
    )

    sql, params = foster_started[0]
    # Idempotence guard from ``record_event`` is the canonical contract
    # for LIFECYCLE-02 acceptance.
    assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql
    # Positional params for ``record_event`` (10 columns). The service
    # supplies animal_id from the persisted row, the timestamp from
    # ``fecha_inicio`` (NOT now() — historic data), and the source
    # entity fields from the new ``acogidas`` row.
    assert params[0] == ANIMAL_UUID
    assert params[1] == LifecycleEventType.FOSTER_STARTED.value
    assert params[2] == "2026-07-04"  # event_timestamp == fecha_inicio
    assert params[3] is None  # caused_by_event_id — no causal parent for entry
    assert params[4] == "acogidas"  # source_entity_type
    assert params[5] == ACOGIDA_UUID  # source_entity_id
    assert params[6] is None  # legacy_source_table
    assert params[7] is None  # legacy_source_id
    # metadata is serialised to JSON when present, None when absent.
    assert params[8] is None
    # ``created_by`` records the service-layer call site as the actor.
    assert params[9] == "acogidas.create_acogida"


def test_create_acogida_emits_intake_closed_by_foster_event() -> None:
    """``create_acogida`` closes the previous INTAKE situation event-sourced.

    The transition from ``Albergue`` (an active ``entradas`` row) to
    ``Acogida`` is recorded in the event log as
    ``INTAKE_CLOSED_BY_FOSTER`` via ``close_previous_situation(category=
    "INTAKE")``. Per AGENTS.md §33.4 the closing is event-sourced — the
    service does NOT issue an ``UPDATE`` against ``entradas`` to set
    ``fecha_salida``.
    """
    executor = FakeSqlExecutor()

    acogidas_service.create_acogida(executor, _params_minimal())

    inserts = _lifecycle_event_inserts(executor.calls)
    closing_events = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == CLOSING_EVENT_BY_CATEGORY["INTAKE"]
    ]
    assert len(closing_events) == 1, (
        f"create_acogida MUST emit exactly one INTAKE_CLOSED_BY_FOSTER "
        f"closing event; got {len(closing_events)}"
    )

    sql, params = closing_events[0]
    # Idempotence guard from ``close_previous_situation`` matches
    # ``record_event``'s pattern (same natural key).
    assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql
    # Positional params for ``close_previous_situation`` (7 columns).
    assert params[0] == ANIMAL_UUID
    assert params[1] == "INTAKE_CLOSED_BY_FOSTER"
    assert params[2] == "2026-07-04"  # event_timestamp == fecha_inicio
    # ``caused_by_event_id`` is None — the trigger event id isn't
    # threaded through from ``record_event`` in the current service
    # implementation (the closing event is emitted alongside the entry
    # event, not after fetching the inserted row's id).
    assert params[3] is None
    assert params[4] == "acogidas"  # source_entity_type
    assert params[5] == ACOGIDA_UUID  # source_entity_id
    # The closing event is sourced from the acogidas side; no legacy
    # fields. ``created_by`` falls back to the use case default.
    assert params[6] == "lifecycle.close_previous_situation"

    # Source-of-truth invariant (AGENTS.md §33.4): the closing is
    # event-sourced, never UPDATE against ``entradas`` / ``acogidas``.
    for sql_stmt, _params_stmt in executor.calls:
        normalized = sql_stmt.strip().upper()
        assert not normalized.startswith("UPDATE ENTRADAS"), (
            f"create_acogida MUST NOT UPDATE entradas; got: {sql_stmt!r}"
        )


def test_create_acogida_updates_animal_current_state() -> None:
    """``create_acogida`` refreshes the ``animal_current_state`` cache.

    The cascade re-derives the state after every lifecycle event insert
    (PR-A contract). The service calls ``actualizar_estado_animal``
    twice on the create path — once implicitly inside ``record_event``
    (after the FOSTER_STARTED INSERT) and once explicitly after
    ``close_previous_situation`` (after the INTAKE_CLOSED_BY_FOSTER
    INSERT). The two UPSERTs MUST carry the same ``animal_id`` so the
    cache converges on the latest derived state.
    """
    executor = FakeSqlExecutor()

    acogidas_service.create_acogida(executor, _params_minimal())

    cache_upserts = _animal_current_state_inserts(executor.calls)
    assert len(cache_upserts) >= 1, (
        f"create_acogida MUST refresh animal_current_state via "
        f"actualizar_estado_animal; got {len(cache_upserts)} upserts. "
        f"All calls: {[sql.strip()[:60] for sql, _ in executor.calls]}"
    )

    # Every UPSERT carries the same animal_id (the new stay's animal).
    for _sql, params in cache_upserts:
        assert params[0] == ANIMAL_UUID, (
            f"animal_current_state UPSERT must carry the new stay's "
            f"animal_id; got {params[0]!r}"
        )

    # The UPSERT SQL uses the natural-key arbiter pattern (PR-C).
    sql_first, _ = cache_upserts[0]
    assert "ON CONFLICT (animal_id) DO UPDATE" in sql_first
    assert "INSERT INTO animal_current_state" in sql_first


# --- close_acogida: lifecycle event emission ------------------------------


def test_close_acogida_emits_foster_returned_event() -> None:
    """``close_acogida`` writes a ``FOSTER_RETURNED`` event into the log.

    The event timestamp falls back to ``str(date.today())`` when the
    closed row's ``fecha_final`` is missing (defensive — the close
    path always stamps ``CURRENT_DATE`` so this branch is rarely hit,
    but the call site MUST stay safe under partial data).
    """
    executor = FakeSqlExecutor()

    result = acogidas_service.close_acogida(executor, ACOGIDA_UUID)

    assert result is not None
    assert result.id == ACOGIDA_UUID

    inserts = _lifecycle_event_inserts(executor.calls)
    foster_returned = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == LifecycleEventType.FOSTER_RETURNED.value
    ]
    assert len(foster_returned) == 1, (
        f"close_acogida MUST emit exactly one FOSTER_RETURNED event; "
        f"got {len(foster_returned)}"
    )

    sql, params = foster_returned[0]
    assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql
    assert params[0] == ANIMAL_UUID
    assert params[1] == "FOSTER_RETURNED"
    # ``fecha_final`` is stamped by the UPDATE so the returned row
    # carries today's date — the event timestamp matches it.
    assert params[2] == result.fecha_final
    assert params[3] is None  # caused_by_event_id
    assert params[4] == "acogidas"  # source_entity_type
    assert params[5] == ACOGIDA_UUID  # source_entity_id
    assert params[6] is None  # legacy_source_table
    assert params[7] is None  # legacy_source_id
    assert params[8] is None  # metadata
    assert params[9] == "acogidas.close_acogida"

    # close_acogida MUST NOT emit any closing-event row from
    # close_previous_situation — closing the foster stay is a single
    # FOSTER_RETURNED event (the transition into adoption / return-to-
    # shelter is a separate use case).
    closing_events = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] in (
            "INTAKE_CLOSED_BY_FOSTER",
            "FOSTER_CLOSED_BY_ADOPTION",
            "ADOPTION_RETURNED",
        )
    ]
    assert closing_events == [], (
        f"close_acogida MUST NOT emit a closing-event row; "
        f"got {closing_events!r}"
    )


def test_close_acogida_updates_animal_current_state() -> None:
    """``close_acogida`` refreshes the ``animal_current_state`` cache.

    Same PR-A contract as the create path: the cache MUST be refreshed
    after the FOSTER_RETURNED event lands. The UPSERT targets the
    closed stay's animal so any other active placements (intakes,
    adoptions) can be re-evaluated against the now-closed foster row.
    """
    executor = FakeSqlExecutor()

    acogidas_service.close_acogida(executor, ACOGIDA_UUID)

    cache_upserts = _animal_current_state_inserts(executor.calls)
    assert len(cache_upserts) >= 1, (
        f"close_acogida MUST refresh animal_current_state; got "
        f"{len(cache_upserts)} upserts"
    )

    for _sql, params in cache_upserts:
        assert params[0] == ANIMAL_UUID, (
            f"animal_current_state UPSERT must carry the closed stay's "
            f"animal_id; got {params[0]!r}"
        )

    # The first UPSERT carries the canonical ON CONFLICT clause.
    sql_first, _ = cache_upserts[0]
    assert "ON CONFLICT (animal_id) DO UPDATE" in sql_first

    # The cache refresh fires AFTER the FOSTER_RETURNED INSERT — the
    # ordering matters because the cascade reads the active-placements
    # collections and must see the closed stay's ``fecha_final`` (the
    # ``acogidas`` UPDATE happens before both the event INSERT and the
    # cache refresh).
    lifecycle_insert_indexes = [
        i
        for i, (sql, _params) in enumerate(executor.calls)
        if "INSERT INTO animal_lifecycle_events" in sql
    ]
    cache_upsert_indexes = [
        i
        for i, (sql, _params) in enumerate(executor.calls)
        if "INSERT INTO animal_current_state" in sql
    ]
    assert lifecycle_insert_indexes, "no lifecycle event INSERT found"
    assert cache_upsert_indexes, "no animal_current_state UPSERT found"
    assert min(lifecycle_insert_indexes) < min(cache_upsert_indexes), (
        "the FOSTER_RETURNED INSERT must precede the cache refresh so "
        "the cascade re-derives with the new event in the log"
    )


# --- payload-shape sanity (anti-regression) -------------------------------


def test_lifecycle_event_metadata_is_serialised_as_json_string() -> None:
    """Defensive: ensure the test fixture does not silently break the JSON shape.

    Pins the metadata column contract (``json.dumps(metadata)`` when
    present, ``None`` when absent) — the lifecycle_events module asserts
    ``isinstance(params[8], str)`` for non-None metadata. If a future
    refactor passes a ``dict`` directly, this test catches it before
    the SQL layer rejects the wrong type.
    """
    from app.modules.animals.lifecycle_events import record_event

    executor = FakeSqlExecutor()

    # Use the canonical ``record_event`` API directly to pin the shape.
    record_event(
        executor,
        animal_id=ANIMAL_UUID,
        event_type=LifecycleEventType.INTAKE_STARTED,
        event_timestamp="2026-07-27T00:00:00+00:00",
        created_by="test-helper",
        metadata={"legacy_pk": 42},
    )

    inserts = _lifecycle_event_inserts(executor.calls)
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert isinstance(params[8], str), (
        f"metadata MUST be serialised via json.dumps; got {type(params[8]).__name__}"
    )
    assert json.loads(params[8]) == {"legacy_pk": 42}

