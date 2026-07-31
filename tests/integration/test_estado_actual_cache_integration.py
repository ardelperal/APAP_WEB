"""Integration tests for the estado_actual_animal cache update (issue #69).

Tests that ``record_event`` calls ``actualizar_estado_animal`` after
inserting a lifecycle event, so the ``animal_current_state`` cache
table is kept in sync with the event log.

Requires a real PostgreSQL instance (APAP_TEST_POSTGRES_DSN).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.animals.lifecycle_events import (
    LifecycleEventType,
    actualizar_estado_animal,
    record_event,
)
from tests.integration.conftest import _EphemeralPostgres


@pytest.mark.integration
def test_record_event_updates_cache(ephemeral_postgres: _EphemeralPostgres) -> None:
    """After recording an event, the cache row exists with the correct state."""
    animal_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())
    event_ts = "2026-07-27T10:00:00+00:00"

    # Record an INTAKE_STARTED event.
    with ephemeral_postgres.connection() as conn:
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.INTAKE_STARTED,
            event_timestamp=event_ts,
            created_by=creator_id,
        )

    # Verify the cache row was created.
    rows = ephemeral_postgres.execute(
        "SELECT animal_id, current_state FROM animal_current_state WHERE animal_id = %s",
        (animal_id,),
    )
    assert len(rows) == 1
    assert rows[0]["animal_id"] == animal_id
    # INTAKE_STARTED maps to 'Pendiente de Entrada'.
    assert rows[0]["current_state"] == "Pendiente de Entrada"


@pytest.mark.integration
def test_record_event_sets_correct_state_for_foster(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """FOSTER_STARTED event results in 'Acogida' state in the cache."""
    animal_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())

    with ephemeral_postgres.connection() as conn:
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.FOSTER_STARTED,
            event_timestamp="2026-07-27T10:00:00+00:00",
            created_by=creator_id,
        )

    rows = ephemeral_postgres.execute(
        "SELECT current_state FROM animal_current_state WHERE animal_id = %s",
        (animal_id,),
    )
    assert len(rows) == 1
    assert rows[0]["current_state"] == "Acogida"


@pytest.mark.integration
def test_record_event_sets_correct_state_for_adoption(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """ADOPTION_STARTED event results in 'Adoptado' state in the cache."""
    animal_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())

    with ephemeral_postgres.connection() as conn:
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.ADOPTION_STARTED,
            event_timestamp="2026-07-27T10:00:00+00:00",
            created_by=creator_id,
        )

    rows = ephemeral_postgres.execute(
        "SELECT current_state FROM animal_current_state WHERE animal_id = %s",
        (animal_id,),
    )
    assert len(rows) == 1
    assert rows[0]["current_state"] == "Adoptado"


@pytest.mark.integration
def test_cache_is_idempotent_on_re_record(ephemeral_postgres: _EphemeralPostgres) -> None:
    """Recording the same event twice does not create duplicate cache rows."""
    animal_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())
    event_ts = "2026-07-27T10:00:00+00:00"

    with ephemeral_postgres.connection() as conn:
        # Insert twice (same logical event via ON CONFLICT DO NOTHING).
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.INTAKE_COMPLETED,
            event_timestamp=event_ts,
            created_by=creator_id,
        )
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.INTAKE_COMPLETED,
            event_timestamp=event_ts,
            created_by=creator_id,
        )

    # Should still have exactly 1 cache row.
    rows = ephemeral_postgres.execute(
        "SELECT COUNT(*) as cnt FROM animal_current_state WHERE animal_id = %s",
        (animal_id,),
    )
    assert rows[0]["cnt"] == 1


@pytest.mark.integration
def test_actualizar_estado_animal_standalone(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """``actualizar_estado_animal`` can be called directly (not just via record_event)."""
    animal_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())

    # Insert an event first so the animal has a history.
    with ephemeral_postgres.connection() as conn:
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.FOSTER_STARTED,
            event_timestamp="2026-07-27T10:00:00+00:00",
            created_by=creator_id,
        )

    # Now update the cache directly.
    with ephemeral_postgres.connection() as conn:
        actualizar_estado_animal(conn, animal_id=animal_id)

    rows = ephemeral_postgres.execute(
        "SELECT current_state FROM animal_current_state WHERE animal_id = %s",
        (animal_id,),
    )
    assert len(rows) == 1
    # FOSTER_STARTED → Acogida.
    assert rows[0]["current_state"] == "Acogida"


@pytest.mark.integration
def test_cache_has_state_changed_at_timestamp(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """The cache row has state_changed_at set to a recent timestamp."""
    animal_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())

    with ephemeral_postgres.connection() as conn:
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.DEATH_RECORDED,
            event_timestamp="2026-07-27T10:00:00+00:00",
            created_by=creator_id,
        )

    rows = ephemeral_postgres.execute(
        "SELECT state_changed_at FROM animal_current_state WHERE animal_id = %s",
        (animal_id,),
    )
    assert len(rows) == 1
    assert rows[0]["state_changed_at"] is not None


@pytest.mark.integration
def test_record_event_caches_death_state(ephemeral_postgres: _EphemeralPostgres) -> None:
    """DEATH_RECORDED results in a 'Fallecido...' state in the cache."""
    animal_id = str(uuid.uuid4())
    creator_id = str(uuid.uuid4())

    with ephemeral_postgres.connection() as conn:
        record_event(
            conn,
            animal_id=animal_id,
            event_type=LifecycleEventType.DEATH_RECORDED,
            event_timestamp="2026-07-27T10:00:00+00:00",
            created_by=creator_id,
        )

    rows = ephemeral_postgres.execute(
        "SELECT current_state FROM animal_current_state WHERE animal_id = %s",
        (animal_id,),
    )
    assert len(rows) == 1
    assert rows[0]["current_state"] == "Fallecido (Albergue)"
