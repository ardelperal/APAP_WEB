"""Integration tests for ``app.modules.entradas.queries``.

Executes the batch commit CTE against the real Postgres fixture to validate
that the atomic-copy contract documented in ``batch_service._COMMIT_BATCH_SQL``
holds against a real database — not just against the ``httpx.MockTransport``
handler in ``tests/test_entradas_batch.py``.

Issue #632 / audit #631: the staged-rows → entradas CTE rollback semantics
cannot be verified against a mock. If a row in the staged batch collides
with an existing entrada on (animal_id, fecha_entrada), or violates a
foreign key, PostgreSQL must roll back the entire copy AND leave the
staging rows intact so the operator can inspect via ``get_batch`` and
retry or cancel.

This file closes the P0 gap documented in
``docs/quality/test-audit.md`` §Critical-gaps point 1.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from app.modules.entradas import batch_service
from tests.integration.conftest import _EphemeralPostgres

# Pull the SQL constants directly from the module under test. They are
# public-by-convention (no leading underscore on the SQL itself; the
# surrounding functions are private). Importing them keeps this test
# pinned to the exact same string the production service emits; if the
# CTE is ever refactored, the test diff reveals it.
_COMMIT_BATCH_SQL = batch_service._COMMIT_BATCH_SQL
_INSERT_STAGING_SQL = batch_service._INSERT_STAGING_SQL


def _seed_animal(ep: _EphemeralPostgres, nchip: str) -> str:
    """INSERT a minimal animales row and return its UUID."""
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', '{nchip}', 'Test Animal', 'CANINA', 'H', '2020-01-01', now(), true) "
        f"RETURNING id"
    )
    return animal_id


def _seed_voluntario(ep: _EphemeralPostgres) -> str:
    """INSERT a minimal voluntarios row and return its UUID."""
    voluntario_id = str(uuid4())
    ep.execute(
        f"INSERT INTO voluntarios (id, voluntario, email, activo, fecha_alta) "
        f"VALUES ('{voluntario_id}', 'Vol Test', 'vol-{uuid4().hex[:8]}@test.com', true, now()) "
        f"RETURNING id"
    )
    return voluntario_id


def _stage_row(
    ep: _EphemeralPostgres,
    *,
    batch_id: str,
    sequence: int,
    animal_id: str,
    fecha_entrada: str,
    motivo: str = "Rescate",
) -> None:
    """INSERT one row into entradas_batch_staging.

    The production ``_INSERT_STAGING_SQL`` is a plain ``INSERT`` (no
    ``RETURNING``), so we must bypass the ``_EphemeralPostgres.execute()``
    helper — that helper unconditionally calls ``cur.fetchall()`` and
    raises ``ProgrammingError`` on non-SELECT statements. We open the
    connection directly and execute the INSERT via the same
    placeholder-rewrite path the helper uses.
    """
    # pylint: disable=import-outside-toplevel
    from tests.integration.conftest import (
        _expand_params_for_placeholder_style,
    )
    query, params = _expand_params_for_placeholder_style(
        _INSERT_STAGING_SQL,
        [batch_id, sequence, animal_id, None, fecha_entrada, "Albergue", motivo, None],
    )
    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)


@pytest.mark.integration
def test_commit_batch_cte_rolls_back_on_unique_violation(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Commit CTE must rollback the whole copy when a staged row collides
    with an existing entrada on the natural key (animal_id, fecha_entrada).

    The pre-existing entrada acts as the constraint that the staged row
    will violate. The other staged rows must NOT land in ``entradas`` and
    the staging rows must remain intact for operator inspection.
    """
    ep = ephemeral_postgres
    animal_a = _seed_animal(ep, "CHIP-A-001")
    animal_b = _seed_animal(ep, "CHIP-B-001")
    animal_c = _seed_animal(ep, "CHIP-C-001")
    _seed_voluntario(ep)

    # Pre-existing entrada that will collide with the second staged row.
    collision_date = "2026-07-15"
    ep.execute(
        f"INSERT INTO entradas (animal_id, fecha_entrada, motivo, observaciones) "
        f"VALUES ('{animal_b}', '{collision_date}', 'Existing', 'Pre-existing row') "
        f"RETURNING id"
    )

    batch_id = str(uuid4())
    _stage_row(ep, batch_id=batch_id, sequence=1, animal_id=animal_a, fecha_entrada="2026-07-14")
    _stage_row(ep, batch_id=batch_id, sequence=2, animal_id=animal_b, fecha_entrada=collision_date)
    _stage_row(ep, batch_id=batch_id, sequence=3, animal_id=animal_c, fecha_entrada="2026-07-16")

    # Sanity: staging has three rows before the commit attempt.
    pre_staging = ep.execute(
        "SELECT sequence FROM entradas_batch_staging WHERE batch_id = %s ORDER BY sequence",
        [batch_id],
    )
    assert [r["sequence"] for r in pre_staging] == [1, 2, 3]

    # The commit CTE must raise psycopg.errors.UniqueViolation against
    # the real Postgres engine — this is the behaviour the unit-test
    # mock cannot verify.
    with pytest.raises(psycopg.errors.UniqueViolation):
        ep.execute(_COMMIT_BATCH_SQL, [batch_id])

    # Post-condition 1: no new rows landed in ``entradas``. The pre-existing
    # collision row is the only one; animals A and C must be absent.
    entradas_after = ep.execute(
        "SELECT animal_id, fecha_entrada FROM entradas ORDER BY fecha_entrada"
    )
    assert len(entradas_after) == 1
    assert str(entradas_after[0]["animal_id"]) == animal_b
    assert str(entradas_after[0]["fecha_entrada"]) == collision_date

    # Post-condition 2: staging rows are still intact. The operator can
    # inspect via get_batch and decide whether to cancel or fix and retry.
    post_staging = ep.execute(
        "SELECT sequence FROM entradas_batch_staging WHERE batch_id = %s ORDER BY sequence",
        [batch_id],
    )
    assert [r["sequence"] for r in post_staging] == [1, 2, 3]


@pytest.mark.integration
def test_commit_batch_cte_rolls_back_on_fk_violation(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Commit CTE must rollback the whole copy when a staged row references
    a non-existent animal_id.

    The FK on ``entradas.animal_id REFERENCES animales(id)`` fires when the
    CTE attempts to INSERT a row pointing at an animal that does not exist.
    This is the second flavour of constraint that the staging pattern must
    protect against; it complements the UNIQUE-violation atom above.
    """
    ep = ephemeral_postgres
    animal_a = _seed_animal(ep, "CHIP-A-002")
    _seed_voluntario(ep)

    # An animal_id that does not exist anywhere. The CTE must reject it.
    ghost_animal_id = str(uuid4())

    batch_id = str(uuid4())
    _stage_row(ep, batch_id=batch_id, sequence=1, animal_id=animal_a, fecha_entrada="2026-08-01")
    _stage_row(
        ep,
        batch_id=batch_id,
        sequence=2,
        animal_id=ghost_animal_id,
        fecha_entrada="2026-08-02",
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        ep.execute(_COMMIT_BATCH_SQL, [batch_id])

    # No row landed in ``entradas``.
    entradas_after = ep.execute("SELECT animal_id FROM entradas")
    assert entradas_after == []

    # Staging rows remain intact for operator inspection.
    post_staging = ep.execute(
        "SELECT sequence FROM entradas_batch_staging WHERE batch_id = %s ORDER BY sequence",
        [batch_id],
    )
    assert [r["sequence"] for r in post_staging] == [1, 2]


@pytest.mark.integration
def test_commit_batch_cte_succeeds_when_no_constraint_violated(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Happy-path control: when no row violates a constraint, the CTE
    commits all staged rows to ``entradas`` AND clears the staging table.

    This is the counterpart to the two rollback atoms: it pins the
    success-path semantics so a future CTE refactor that accidentally
    over-rolls back or under-commits would surface here.
    """
    ep = ephemeral_postgres
    animal_a = _seed_animal(ep, "CHIP-A-003")
    animal_b = _seed_animal(ep, "CHIP-B-003")
    _seed_voluntario(ep)

    batch_id = str(uuid4())
    _stage_row(ep, batch_id=batch_id, sequence=1, animal_id=animal_a, fecha_entrada="2026-09-01")
    _stage_row(ep, batch_id=batch_id, sequence=2, animal_id=animal_b, fecha_entrada="2026-09-02")

    rows = ep.execute(_COMMIT_BATCH_SQL, [batch_id])

    # Two inserted rows returned by the CTE (one per staged row).
    assert len(rows) == 2
    assert {str(r["animal_id"]) for r in rows} == {animal_a, animal_b}

    # Staging cleared for this batch.
    post_staging = ep.execute(
        "SELECT sequence FROM entradas_batch_staging WHERE batch_id = %s",
        [batch_id],
    )
    assert post_staging == []