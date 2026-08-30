"""Lifecycle-event emission tests for ``app.modules.adopciones.service``.

LIFECYCLE-02 (issue #32): every adoption transition in the ``adopciones``
slice MUST emit the matching event into ``animal_lifecycle_events`` so
the event log is the single source of truth for state derivation. The
use case under test lives in ``app.modules.adopciones.service`` — the
routes stay pure HTTP glue.

What these tests pin
--------------------

``create_adopcion`` writes three rows into ``animal_lifecycle_events``
inside the same DB transaction as the ``adopciones`` INSERT:

  1. ``ADOPTION_STARTED`` — the entry into the adoption.
  2. ``FOSTER_CLOSED_BY_ADOPTION`` — emitted by
     ``close_previous_situation(category="FOSTER")`` to record the
     Acogida -> Adoptado transition (the previous foster situation is
     closed event-sourced, not via an ``acogidas`` UPDATE).
  3. ``actualizar_estado_animal`` is called twice (once inside
     ``record_event`` and once explicitly after the closing event) so the
     ``animal_current_state`` cache row reflects the new ``Adoptado``
     state.

``update_adopcion`` writes one row into ``animal_lifecycle_events``
when ``fecha_devolucion`` transitions from ``None`` to a date string
(the family returned the animal):

  1. ``ADOPTION_RETURNED`` — the exit out of the adoption.
  2. ``actualizar_estado_animal`` is called once after the event INSERT
     so the cache row reverts to ``Acogida`` / ``Albergue`` / etc.
     depending on the other active placements.

Test pattern
------------

A ``FakeSqlExecutor`` records every ``execute_sql`` call so the
service layer can be exercised without a live database. The pattern
mirrors the one in
``tests/test_acogidas_lifecycle_events.py`` and
``tests/test_lifecycle_close_previous_situation_emits_closing_event.py``
— those are the canonical references for this executor shape in the
lifecycle slice.

Scope
------

This file is scoped to the service-layer event emission. The route
layer already pins the SQL shape via the FakeSqlExecutor patterns in
``tests/test_adopciones.py``; the ``adopciones`` queries are covered
by ``tests/test_adopciones.py`` (the CTE-shaped INSERT / UPDATE). Here
we focus on the new lifecycle contract that LIFECYCLE-02 adds on top
of the existing CRUD.
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.adopciones import service as adopciones_service
from app.modules.animals.lifecycle_events import LifecycleEventType
from app.modules.lifecycle.application.close_previous_situation import (
    CLOSING_EVENT_BY_CATEGORY,
)

# --- helpers --------------------------------------------------------------


ADOPCION_UUID = "33333333-3333-3333-3333-333333333333"
ANIMAL_UUID = "11111111-1111-1111-1111-111111111111"


class FakeSqlExecutor:
    """Stub executor that records every ``execute_sql`` call.

    The executor handles every SQL shape that the ``adopciones`` service
    is expected to issue under the lifecycle-aware code path:

      * FK validation SELECTs (animales / voluntarios / entradas) —
        each returns a "valid active row" so the validation chain
        passes.
      * ``INSERT INTO adopciones`` (CTE-shaped) and
        ``UPDATE adopciones SET ...`` (CTE-shaped) — returns the canned
        row so the service can map it back to an :class:`Adopcion`.
      * ``SELECT ... FROM adopciones WHERE id = $1`` (the
        ``get_adopcion_by_id`` lookup ``update_adopcion`` runs to
        capture the previous ``fecha_devolucion``).
      * Every other call (lifecycle events INSERT, cache UPSERT, the
        cascade's ficha + active-placements SELECTs) returns an empty
        row list, which the cascade treats as "no other active
        placements".

    Mirrors the same pattern as
    ``tests/test_acogidas_lifecycle_events.py`` and
    ``tests/test_lifecycle_close_previous_situation_emits_closing_event.py``.
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
        if normalized.startswith("SELECT id FROM animales"):
            return [{"id": params_list[0]}]
        if normalized.startswith("SELECT id FROM voluntarios"):
            return [{"id": params_list[0]}]
        if normalized.startswith("SELECT id FROM entradas"):
            return [{"id": params_list[0]}]

        # ``update_adopcion`` captures the previous row state BEFORE the
        # UPDATE so it can detect the active -> returned transition.
        # Return a canonical row whose ``fecha_devolucion`` is None so
        # the create-path tests stay on the "no transition" branch.
        if normalized.startswith("SELECT") and "FROM adopciones" in normalized:
            return [self._update_row or _default_insert_row()]

        if "INSERT INTO adopciones" in normalized:
            return [self._insert_row or _default_insert_row()]
        if "UPDATE adopciones" in normalized:
            return [self._update_row or _default_update_row()]
        return []


def _default_insert_row() -> dict[str, Any]:
    """Canonical returned row for the ``INSERT INTO adopciones`` mock.

    ``fecha_devolucion`` is None so the create-path tests stay on the
    "no ADOPTION_RETURNED transition" branch.
    """
    return {
        "id": ADOPCION_UUID,
        "animal_id": ANIMAL_UUID,
        "voluntario_seguimiento_id": None,
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": None,
        "donativo_preadopcion": None,
        "donativo_adopcion": None,
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": None,
        "observaciones": "Adopción responsable",
        "tipo_adopcion": "regular",
        "responsable_adopcion_id": None,
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
    }


def _default_update_row() -> dict[str, Any]:
    """Canonical returned row for the ``UPDATE adopciones`` mock.

    Used by the ADOPTION_RETURNED tests — ``fecha_devolucion`` is set
    so the transition detection in ``update_adopcion`` fires.
    """
    return {
        **_default_insert_row(),
        "fecha_devolucion": "2026-08-15",
        "updated_at": "2026-08-15T10:00:00Z",
    }


def _params_minimal() -> dict[str, Any]:
    """Minimal valid params dict for ``create_adopcion``."""
    return {
        "animal_id": ANIMAL_UUID,
        "voluntario_seguimiento_id": None,
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": None,
        "donativo_preadopcion": None,
        "donativo_adopcion": None,
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": None,
        "observaciones": "Adopción responsable",
        "tipo_adopcion": "regular",
        "responsable_adopcion_id": None,
    }


def _params_returned() -> dict[str, Any]:
    """Params dict for ``update_adopcion`` that sets ``fecha_devolucion``.

    Mirrors ``_params_minimal`` but with the return date set so the
    active -> returned transition fires in ``update_adopcion``.
    """
    return {**_params_minimal(), "fecha_devolucion": "2026-08-15"}


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


# --- create_adopcion: lifecycle event emission ----------------------------


def test_create_adopcion_emits_adoption_started_event() -> None:
    """``create_adopcion`` writes an ``ADOPTION_STARTED`` event into the log.

    The event MUST be emitted via the canonical
    ``record_event(...)`` use case so the ``ON CONFLICT (animal_id,
    event_type, event_timestamp) DO NOTHING`` idempotence guard applies
    (issue #32 acceptance). The closing event from
    ``close_previous_situation`` is a separate INSERT — that one is
    pinned in a sibling test.
    """
    executor = FakeSqlExecutor()

    result = adopciones_service.create_adopcion(executor, _params_minimal())

    assert isinstance(result, adopciones_service.Adopcion)

    inserts = _lifecycle_event_inserts(executor.calls)
    adoption_started = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == LifecycleEventType.ADOPTION_STARTED.value
    ]
    assert len(adoption_started) == 1, (
        f"create_adopcion MUST emit exactly one ADOPTION_STARTED event; "
        f"got {len(adoption_started)} matching INSERTs across "
        f"{len(inserts)} lifecycle-event INSERTs"
    )

    sql, params = adoption_started[0]
    # Idempotence guard from ``record_event`` is the canonical contract
    # for LIFECYCLE-02 acceptance.
    assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql
    # Positional params for ``record_event`` (10 columns). The service
    # supplies animal_id from the persisted row, the timestamp from
    # ``fecha_adopcion`` (NOT now() — historic data), and the source
    # entity fields from the new ``adopciones`` row.
    assert params[0] == ANIMAL_UUID
    assert params[1] == LifecycleEventType.ADOPTION_STARTED.value
    assert params[2] == "2026-07-04"  # event_timestamp == fecha_adopcion
    assert params[3] is None  # caused_by_event_id — no causal parent for entry
    assert params[4] == "adopciones"  # source_entity_type
    assert params[5] == ADOPCION_UUID  # source_entity_id
    assert params[6] is None  # legacy_source_table
    assert params[7] is None  # legacy_source_id
    # metadata is serialised to JSON when present, None when absent.
    assert params[8] is None
    # ``created_by`` records the service-layer call site as the actor.
    assert params[9] == "adopciones.create_adopcion"


def test_create_adopcion_emits_foster_closed_by_adoption_event() -> None:
    """``create_adopcion`` closes the previous FOSTER situation event-sourced.

    The transition from ``Acogida`` (an active ``acogidas`` row) to
    ``Adoptado`` is recorded in the event log as
    ``FOSTER_CLOSED_BY_ADOPTION`` via
    ``close_previous_situation(category="FOSTER")``. Per AGENTS.md §33.4
    the closing is event-sourced — the service does NOT issue an
    ``UPDATE`` against ``acogidas`` to set ``fecha_final``.
    """
    executor = FakeSqlExecutor()

    adopciones_service.create_adopcion(executor, _params_minimal())

    inserts = _lifecycle_event_inserts(executor.calls)
    closing_events = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == CLOSING_EVENT_BY_CATEGORY["FOSTER"]
    ]
    assert len(closing_events) == 1, (
        f"create_adopcion MUST emit exactly one FOSTER_CLOSED_BY_ADOPTION "
        f"closing event; got {len(closing_events)}"
    )

    sql, params = closing_events[0]
    # Idempotence guard from ``close_previous_situation`` matches
    # ``record_event``'s pattern (same natural key).
    assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql
    # Positional params for ``close_previous_situation`` (7 columns).
    assert params[0] == ANIMAL_UUID
    assert params[1] == "FOSTER_CLOSED_BY_ADOPTION"
    assert params[2] == "2026-07-04"  # event_timestamp == fecha_adopcion
    # ``caused_by_event_id`` is None — the trigger event id isn't
    # threaded through from ``record_event`` in the current service
    # implementation (the closing event is emitted alongside the entry
    # event, not after fetching the inserted row's id).
    assert params[3] is None
    assert params[4] == "adopciones"  # source_entity_type
    assert params[5] == ADOPCION_UUID  # source_entity_id
    # The closing event is sourced from the adopciones side; no legacy
    # fields. ``created_by`` falls back to the use case default.
    assert params[6] == "lifecycle.close_previous_situation"

    # Source-of-truth invariant (AGENTS.md §33.4): the closing is
    # event-sourced, never UPDATE against ``entradas`` / ``acogidas`` /
    # ``adopciones``.
    for sql_stmt, _params_stmt in executor.calls:
        normalized = sql_stmt.strip().upper()
        assert not normalized.startswith("UPDATE ACOGIDAS"), (
            f"create_adopcion MUST NOT UPDATE acogidas; got: {sql_stmt!r}"
        )
        assert not normalized.startswith("UPDATE ENTRADAS"), (
            f"create_adopcion MUST NOT UPDATE entradas; got: {sql_stmt!r}"
        )


def test_create_adopcion_updates_animal_current_state() -> None:
    """``create_adopcion`` refreshes the ``animal_current_state`` cache.

    The cascade re-derives the state after every lifecycle event insert
    (PR-A contract). The service calls ``actualizar_estado_animal``
    twice on the create path — once implicitly inside ``record_event``
    (after the ADOPTION_STARTED INSERT) and once explicitly after
    ``close_previous_situation`` (after the FOSTER_CLOSED_BY_ADOPTION
    INSERT). The two UPSERTs MUST carry the same ``animal_id`` so the
    cache converges on the latest derived state.
    """
    executor = FakeSqlExecutor()

    adopciones_service.create_adopcion(executor, _params_minimal())

    cache_upserts = _animal_current_state_inserts(executor.calls)
    assert len(cache_upserts) >= 1, (
        f"create_adopcion MUST refresh animal_current_state via "
        f"actualizar_estado_animal; got {len(cache_upserts)} upserts. "
        f"All calls: {[sql.strip()[:60] for sql, _ in executor.calls]}"
    )

    # Every UPSERT carries the same animal_id (the new adoption's animal).
    for _sql, params in cache_upserts:
        assert params[0] == ANIMAL_UUID, (
            f"animal_current_state UPSERT must carry the new adoption's "
            f"animal_id; got {params[0]!r}"
        )

    # The UPSERT SQL uses the natural-key arbiter pattern (PR-C).
    sql_first, _ = cache_upserts[0]
    assert "ON CONFLICT (animal_id) DO UPDATE" in sql_first
    assert "INSERT INTO animal_current_state" in sql_first


# --- update_adopcion: ADOPTION_RETURNED emission --------------------------


def test_adopcion_return_updates_animal_state() -> None:
    """``update_adopcion`` writes ``ADOPTION_RETURNED`` when ``fecha_devolucion`` is set.

    The transition detection runs ``get_adopcion_by_id`` BEFORE the
    UPDATE so it can compare the previous ``fecha_devolucion`` to the
    new value. The ``ADOPTION_RETURNED`` event is emitted and the
    ``animal_current_state`` cache is refreshed in the same DB
    transaction as the UPDATE.
    """
    executor = FakeSqlExecutor()

    result = adopciones_service.update_adopcion(
        executor,
        ADOPCION_UUID,
        _params_returned(),
    )

    assert result is not None
    assert result.id == ADOPCION_UUID
    assert result.fecha_devolucion == "2026-08-15"

    inserts = _lifecycle_event_inserts(executor.calls)
    adoption_returned = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == LifecycleEventType.ADOPTION_RETURNED.value
    ]
    assert len(adoption_returned) == 1, (
        f"update_adopcion MUST emit exactly one ADOPTION_RETURNED event "
        f"when fecha_devolucion is set; got {len(adoption_returned)}"
    )

    sql, params = adoption_returned[0]
    assert "ON CONFLICT (animal_id, event_type, event_timestamp) DO NOTHING" in sql
    assert params[0] == ANIMAL_UUID
    assert params[1] == "ADOPTION_RETURNED"
    # event_timestamp == fecha_devolucion (NOT now() — historic data).
    assert params[2] == "2026-08-15"
    assert params[3] is None  # caused_by_event_id
    assert params[4] == "adopciones"  # source_entity_type
    assert params[5] == ADOPCION_UUID  # source_entity_id
    assert params[6] is None  # legacy_source_table
    assert params[7] is None  # legacy_source_id
    assert params[8] is None  # metadata
    assert params[9] == "adopciones.update_adopcion"

    # close_previous_situation is NOT called from the return path
    # (ADOPTION_RETURNED is a single event, not a paired close). The
    # create path is the only one that emits a closing-event row.
    closing_events = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] in (
            "INTAKE_CLOSED_BY_FOSTER",
            "FOSTER_CLOSED_BY_ADOPTION",
        )
    ]
    assert closing_events == [], (
        f"update_adopcion MUST NOT emit a closing-event row; "
        f"got {closing_events!r}"
    )

    # The cache refresh fires AFTER the ADOPTION_RETURNED INSERT — the
    # ordering matters because the cascade reads the active-placements
    # collections and must see the closed adoption's ``fecha_devolucion``
    # (the ``adopciones`` UPDATE happens before both the event INSERT
    # and the cache refresh).
    cache_upserts = _animal_current_state_inserts(executor.calls)
    assert len(cache_upserts) >= 1, (
        f"update_adopcion MUST refresh animal_current_state on the "
        f"return path; got {len(cache_upserts)} upserts"
    )
    for _sql, params in cache_upserts:
        assert params[0] == ANIMAL_UUID, (
            f"animal_current_state UPSERT must carry the returned "
            f"adoption's animal_id; got {params[0]!r}"
        )

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
        "the ADOPTION_RETURNED INSERT must precede the cache refresh so "
        "the cascade re-derives with the new event in the log"
    )


# --- close_previous_situation category mapping ----------------------------


def test_close_previous_situation_passes_correct_category() -> None:
    """``close_previous_situation`` receives ``category="FOSTER"`` for the ADOPTION transition.

    Per AGENTS.md §33.4 the Acogida -> Adoptado transition closes the
    foster situation (``FOSTER_CLOSED_BY_ADOPTION``), not the adoption
    itself. The ``create_adopcion`` service MUST pass
    ``category="FOSTER"`` so the closing event maps to the correct
    branch of ``CLOSING_EVENT_BY_CATEGORY``.

    The check is structural — we can't observe the ``category`` kwarg
    directly through the executor, so we assert the resulting event
    type instead. The mapping ``CLOSING_EVENT_BY_CATEGORY["FOSTER"] ==
    "FOSTER_CLOSED_BY_ADOPTION"`` is the closed source of truth (§4).
    """
    # Sanity check on the closed category set (§4). If a future refactor
    # silently renames the FOSTER branch, the test below would catch it
    # via the wrong event_type.
    assert CLOSING_EVENT_BY_CATEGORY["FOSTER"] == "FOSTER_CLOSED_BY_ADOPTION", (
        "the FOSTER closing event must remain FOSTER_CLOSED_BY_ADOPTION "
        "for create_adopcion to emit the correct lineage"
    )

    executor = FakeSqlExecutor()

    adopciones_service.create_adopcion(executor, _params_minimal())

    inserts = _lifecycle_event_inserts(executor.calls)
    foster_closing = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == CLOSING_EVENT_BY_CATEGORY["FOSTER"]
    ]
    assert len(foster_closing) == 1, (
        f"create_adopcion MUST close the FOSTER situation (not INTAKE / "
        f"ADOPTION); got {len(foster_closing)} closing events. The "
        f"service must pass category='FOSTER' to "
        f"close_previous_situation so the Acogida -> Adoptado "
        f"transition is recorded correctly."
    )

    # ADOPTION_RETURNED is reserved for the Adoptado -> return path
    # (covered by ``test_adopcion_return_updates_animal_state``). The
    # create path MUST NOT emit it.
    adoption_returned = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == LifecycleEventType.ADOPTION_RETURNED.value
    ]
    assert adoption_returned == [], (
        f"create_adopcion MUST NOT emit ADOPTION_RETURNED; got "
        f"{adoption_returned!r}"
    )

    # INTAKE_CLOSED_BY_FOSTER is for the Albergue -> Acogida
    # transition (create_acogida's responsibility). The adopciones
    # create path MUST NOT emit it.
    intake_closing = [
        (sql, params)
        for sql, params in inserts
        if params and len(params) >= 2
        and params[1] == CLOSING_EVENT_BY_CATEGORY["INTAKE"]
    ]
    assert intake_closing == [], (
        f"create_adopcion MUST NOT emit INTAKE_CLOSED_BY_FOSTER; got "
        f"{intake_closing!r}"
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
