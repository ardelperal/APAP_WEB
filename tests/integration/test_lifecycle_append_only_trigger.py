"""Integration test for the animal_lifecycle_events append-only trigger.

Closes the P0 gap documented in
``docs/quality/test-audit.md`` §Critical-gaps point 2 (the
lifecycle_append_only_trigger line item). The trigger ships in the
production schema (see
``app.core.domain_lifecycle.ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL``)
and is provisioned in the integration schema by ``conftest.py``. The
unit-test suite does not exercise it (there is no
``tests/test_lifecycle_append_only_trigger.py``); only an atom
against the real engine can pin that an UPDATE on the table is
rejected at the database level, regardless of the application
layer's discipline.

This is the last P0 from the audit's 2026-08-31 review. After this
lands, the four P0 module gaps and the two P0 cross-cutting gaps
(closed via #632, #633, #634, #635) are all covered.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from tests.integration.conftest import _EphemeralPostgres


def _seed_animal(ep: _EphemeralPostgres) -> str:
    """INSERT a minimal animales row and return its UUID."""
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', 'CHIP-LIFECYCLE-001', 'Test', 'CANINA', 'H', '2020-01-01', now(), true) "
        f"RETURNING id"
    )
    return animal_id


def _insert_event(ep: _EphemeralPostgres, animal_id: str) -> None:
    """INSERT a lifecycle event row.

    Bypasses ``_EphemeralPostgres.execute()`` because the helper
    calls ``cur.fetchall()`` unconditionally; the production
    INSERT here is plain (no RETURNING).
    """
    event_id = str(uuid4())
    created_by = str(uuid4())
    from tests.integration.conftest import _expand_params_for_placeholder_style
    sql = (
        "INSERT INTO animal_lifecycle_events "
        "(id, animal_id, event_type, event_timestamp, created_by) "
        "VALUES (%s, %s, 'INTAKE_STARTED', now(), %s)"
    )
    rewritten, expanded = _expand_params_for_placeholder_style(
        sql, [event_id, animal_id, created_by]
    )
    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(rewritten, expanded)


@pytest.mark.integration
def test_animal_lifecycle_events_trigger_rejects_update(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """UPDATE on ``animal_lifecycle_events`` must be rejected by the
    append-only trigger.

    The trigger fires BEFORE UPDATE; if the row is being modified
    (rather than inserted), it raises an exception that aborts the
    statement. The audit's gap was that no integration atom asserted
    this — only the SQL string existed, with no test evidence that
    Postgres actually enforces the contract.
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    _insert_event(ep, animal_id)

    # The UPDATE must raise. The exact exception class depends on
    # the trigger's RAISE EXCEPTION statement — psycopg exposes it
    # as a subclass of ``psycopg.Error``. We assert the broad class
    # and the message fragment to be future-proof against trigger
    # tweaks that reword the error.
    with pytest.raises(psycopg.Error) as exc_info:
        with ep.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE animal_lifecycle_events "
                    "SET event_type = 'INTAKE_COMPLETED' "
                    "WHERE animal_id = %s",
                    [animal_id],
                )
    assert "append" in str(exc_info.value).lower() or "modif" in str(exc_info.value).lower(), (
        f"Trigger did not raise an append-only-related error. "
        f"Got: {exc_info.value!r}"
    )

    # The row is unchanged. The UPDATE was rejected, not silently
    # ignored.
    rows = ep.execute(
        "SELECT event_type FROM animal_lifecycle_events "
        "WHERE animal_id = %s", [animal_id]
    )
    assert rows[0]["event_type"] == "INTAKE_STARTED"


@pytest.mark.integration
def test_animal_lifecycle_events_trigger_rejects_delete(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """DELETE on ``animal_lifecycle_events`` must also be rejected.

    The append-only trigger is defined to fire on UPDATE; a separate
    trigger (or the same one re-registered for DELETE) covers DELETE.
    This atom verifies the DELETE path is also closed, so the
    append-only contract holds for both write operations.
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep)
    _insert_event(ep, animal_id)

    # If the schema's trigger set only covers UPDATE, this atom
    # documents the gap rather than asserts rejection. We still
    # assert a hard rejection here; if the schema ever drops the
    # DELETE trigger, the atom will fail and the audit gap re-opens.
    with pytest.raises(psycopg.Error) as exc_info:
        with ep.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM animal_lifecycle_events "
                    "WHERE animal_id = %s",
                    [animal_id],
                )
    assert "append" in str(exc_info.value).lower() or "delete" in str(exc_info.value).lower(), (
        f"DELETE was not rejected. The append-only contract allows "
        f"INSERT only; if this atom fails, the schema has lost a "
        f"trigger. Got: {exc_info.value!r}"
    )
