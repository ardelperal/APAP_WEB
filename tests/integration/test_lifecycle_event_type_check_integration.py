"""An existing database gets the widened event_type CHECK (issue #947).

``CREATE TABLE IF NOT EXISTS`` never changes a table that already exists,
so the fix also ships idempotent ``ALTER TABLE`` statements run by the
schema bootstrap. This atom rebuilds the old constraint, runs the upgrade
twice, and proves ``INTAKE_CLOSED_BY_FOSTER`` is accepted afterwards.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.domain_lifecycle import (
    ANIMAL_LIFECYCLE_EVENTS_ADD_EVENT_TYPE_CHECK_SQL,
    ANIMAL_LIFECYCLE_EVENTS_DROP_EVENT_TYPE_CHECK_SQL,
)
from app.core.local_backend.db import LocalPostgresExecutor, QueryError
from tests.integration.conftest import _EphemeralPostgres

pytestmark = pytest.mark.integration

_OLD_CHECK_SQL = (
    "ALTER TABLE animal_lifecycle_events ADD CONSTRAINT "
    "animal_lifecycle_events_event_type_check CHECK (event_type IN ("
    "'INTAKE_STARTED', 'INTAKE_COMPLETED', 'FOSTER_STARTED', 'FOSTER_RETURNED', "
    "'FOSTER_CLOSED_BY_ADOPTION', 'ADOPTION_STARTED', 'ADOPTION_RETURNED', "
    "'OWNER_RETURNED', 'DEATH_RECORDED', 'STATE_CORRECTION', 'CHIP_CHANGED', "
    "'INTAKE_REOPENED', 'FOSTER_REOPENED', 'ADOPTION_REOPENED'))"
)
_INSERT_EVENT_SQL = (
    "INSERT INTO animal_lifecycle_events (animal_id, event_type, event_timestamp, created_by) "
    "VALUES ($1, 'INTAKE_CLOSED_BY_FOSTER', now(), $2)"
)


def _seed_animal(ep: _EphemeralPostgres) -> str:
    animal_id = str(uuid4())
    ep.execute(
        "INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        "VALUES (%s, %s, 'Luna', 'CANINA', 'H', '2019-06-01', now(), true) RETURNING id",
        [animal_id, f"CHIP-947-{animal_id[:8]}"],
    )
    return animal_id


def test_bootstrap_upgrade_lets_an_existing_table_accept_intake_closed_by_foster(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    ep = ephemeral_postgres
    executor = LocalPostgresExecutor(ep.dsn, search_path=ep.schema)
    executor.execute_sql(ANIMAL_LIFECYCLE_EVENTS_DROP_EVENT_TYPE_CHECK_SQL)
    executor.execute_sql(_OLD_CHECK_SQL)
    animal_id = _seed_animal(ep)
    with pytest.raises(QueryError, match="event_type_check"):
        executor.execute_sql(_INSERT_EVENT_SQL, [animal_id, str(uuid4())])

    for _ in range(2):  # the bootstrap replays on every start: must be idempotent
        executor.execute_sql(ANIMAL_LIFECYCLE_EVENTS_DROP_EVENT_TYPE_CHECK_SQL)
        executor.execute_sql(ANIMAL_LIFECYCLE_EVENTS_ADD_EVENT_TYPE_CHECK_SQL)
    executor.execute_sql(_INSERT_EVENT_SQL, [animal_id, str(uuid4())])

    rows = ep.execute(
        "SELECT count(*) AS n FROM animal_lifecycle_events WHERE animal_id = %s "
        "AND event_type = 'INTAKE_CLOSED_BY_FOSTER'",
        [animal_id],
    )
    assert rows[0]["n"] == 1
