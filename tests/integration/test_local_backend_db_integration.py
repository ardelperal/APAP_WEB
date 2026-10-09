"""Integration tests for ``_translate_psycopg_error`` against real Postgres (issue #1293).

The unit tests in ``tests/test_local_backend_db.py`` pin the translator's
SQLSTATE discrimination table against hand-built ``psycopg.errors``
objects (no I/O). They prove the table is correct, but they do not
prove the table lines up with what Postgres actually emits. A unit
test could ship with a typo in the SQLSTATE string and still pass;
only a real Postgres can speak for itself.

The schema the ``ephemeral_postgres`` fixture provisions already
includes the three constraint flavours we need:

- ``UNIQUE (nchip)`` on ``animales`` (SQLSTATE 23505 — unique_violation).
- ``CHECK (especie IN ('CANINA', 'FELINA'))`` and
  ``CHECK (sexo IN ('M', 'H'))`` on ``animales``
  (SQLSTATE 23514 — check_violation).
- ``REFERENCES animales(id)`` on ``entradas.animal_id`` (SQLSTATE 23503
  — foreign_key_violation). The fixture's
  ``tests/integration/conftest.py`` provisions ``entradas`` with that
  FK, so the FK branch needs no extra DDL.

Every test asserts three things at once:

1. The dedicated exception class is raised
   (``UniqueViolationError`` / ``ForeignKeyViolationError`` /
   ``CheckViolationError``).
2. It is an ``isinstance`` of :class:`DataAccessError` — the universal
   Protocol base, so a future ``except DataAccessError`` catch will see
   it.
3. ``__cause__`` is a ``psycopg.Error`` (the original transport error
   kept in the chain so an operator postmortem can still see the
   SQLSTATE in the traceback).

Follows the
``tests/integration/test_cesiones_queries_integration.py`` template
for using the ``ephemeral_postgres`` fixture, and the
``tests/integration/test_local_backend_db.py`` template for
constructing a ``LocalPostgresExecutor`` with the right ``search_path``.

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each test inserts its own seed rows, so the
  test class shares the session-scoped ``ephemeral_postgres`` schema
  without poisoning neighbours.
- Rule 4 (no humo): every assertion pins a concrete return value /
  exception type / ``__cause__`` chain, not absence-of-error.
- Rule 8 (no production mutation): the executor hits the
  ``ephemeral_postgres`` schema only.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from app.core.data_access import (
    CheckViolationError,
    ConstraintViolationError,
    DataAccessError,
    ForeignKeyViolationError,
    UniqueViolationError,
)
from app.core.local_backend.db import LocalPostgresExecutor
from tests.integration.conftest import _EphemeralPostgres

pytestmark = pytest.mark.integration


def _make_executor(ep: _EphemeralPostgres) -> LocalPostgresExecutor:
    """Build a ``LocalPostgresExecutor`` bound to the ephemeral schema.

    Mirrors the helper in ``tests/integration/test_local_backend_db.py``
    so every test stays on the same connection pattern.
    """
    return LocalPostgresExecutor(ep.dsn, search_path=ep.schema)


_INSERT_ANIMAL_SQL = (
    "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
    "VALUES ($1, $2, $3, $4, '2020-01-01')"
)


def test_duplicate_nchip_raises_unique_violation_error(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """A second INSERT with the same NCHIP must raise ``UniqueViolationError``.

    ``animales.nchip`` carries ``UNIQUE NOT NULL`` in the domain schema
    provisioned by ``tests/integration/conftest.py``. A duplicate INSERT
    must translate to :class:`UniqueViolationError` (a
    :class:`ConstraintViolationError` and :class:`DataAccessError`)
    with ``__cause__`` being the original psycopg error so the operator
    postmortem still sees the SQLSTATE in the traceback.
    """
    executor = _make_executor(ephemeral_postgres)
    chip = f"CHIP-1293-UNI-{uuid.uuid4().hex[:8]}"
    executor.execute_sql(_INSERT_ANIMAL_SQL, [chip, "First", "CANINA", "H"])

    with pytest.raises(UniqueViolationError) as exc_info:
        executor.execute_sql(_INSERT_ANIMAL_SQL, [chip, "Second", "CANINA", "H"])

    # The exception carries the upstream message verbatim and is on
    # the dedicated subclass; both the family-level catch and the
    # 409/legacy ``DuplicateKeyError``/``BackendError`` catches still
    # match.
    assert "duplicate" in str(exc_info.value).lower()
    assert isinstance(exc_info.value, UniqueViolationError)
    assert isinstance(exc_info.value, ConstraintViolationError)
    assert isinstance(exc_info.value, DataAccessError)
    assert isinstance(exc_info.value.__cause__, psycopg.Error), (
        "__cause__ must be the original psycopg error so SQLSTATE is "
        "preserved for operator postmortem"
    )
    assert getattr(exc_info.value.__cause__, "sqlstate", None) == "23505"


def test_insert_with_ghost_animal_parent_raises_foreign_key_violation_error(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """An INSERT into ``entradas`` referencing a non-existent ``animal_id``
    must raise ``ForeignKeyViolationError``.

    ``entradas.animal_id`` carries ``REFERENCES animales(id)`` in the
    domain schema; the fixture provisions it. Inserting a UUID that
    has no matching row in ``animales`` violates that FK at the
    database engine, which the executor must translate to
    :class:`ForeignKeyViolationError`.
    """
    executor = _make_executor(ephemeral_postgres)
    ghost_animal_id = str(uuid.uuid4())  # no matching row in animales

    # Minimal columnas NOT NULL: animal_id (FK), fecha_entrada, motivo,
    # observaciones, activo. fecha_alta defaults to now().
    insert_entrada = (
        "INSERT INTO entradas (animal_id, fecha_entrada, motivo, observaciones, activo) "
        "VALUES ($1, '2026-06-01', 'Ingreso', 'Test', true)"
    )

    with pytest.raises(ForeignKeyViolationError) as exc_info:
        executor.execute_sql(insert_entrada, [ghost_animal_id])

    assert isinstance(exc_info.value, ForeignKeyViolationError)
    assert isinstance(exc_info.value, ConstraintViolationError)
    assert isinstance(exc_info.value, DataAccessError)
    assert isinstance(exc_info.value.__cause__, psycopg.Error)
    assert getattr(exc_info.value.__cause__, "sqlstate", None) == "23503"


def test_invalid_especie_raises_check_violation_error(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """An INSERT with ``especie='EQUINA'`` (not in the CHECK set) must
    raise ``CheckViolationError``.

    The ``animales.especie`` column carries
    ``CHECK (especie IN ('CANINA', 'FELINA'))`` in the domain schema.
    The CHECK fires at the database engine, not at the application
    layer; the executor must translate it to
    :class:`CheckViolationError` so domain code can render a
    "valor no permitido" message.
    """
    executor = _make_executor(ephemeral_postgres)
    chip = f"CHIP-1293-CHK-{uuid.uuid4().hex[:8]}"

    with pytest.raises(CheckViolationError) as exc_info:
        # ``especie='EQUINA'`` violates the CHECK constraint.
        executor.execute_sql(
            _INSERT_ANIMAL_SQL,
            [chip, "Bad Especie", "EQUINA", "H"],
        )

    assert isinstance(exc_info.value, CheckViolationError)
    assert isinstance(exc_info.value, ConstraintViolationError)
    assert isinstance(exc_info.value, DataAccessError)
    assert isinstance(exc_info.value.__cause__, psycopg.Error)
    assert getattr(exc_info.value.__cause__, "sqlstate", None) == "23514"


def test_unique_violation_inside_transaction_rolls_back(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """A unique violation raised inside ``transaction()`` propagates
    as ``UniqueViolationError`` AND rolls back the whole unit of work
    (issue #1293).

    Pins the contract that the new ``except DataAccessError`` branch
    inside ``execute_sql`` (which replaced the old
    ``except (QueryError, DatabaseError)`` branch — UniqueViolation
    is no longer a QueryError) still triggers the rollback. The
    sibling row inserted in the same transaction must not survive
    the failure.
    """
    executor = _make_executor(ephemeral_postgres)
    first_chip = f"CHIP-1293-TX-A-{uuid.uuid4().hex[:8]}"
    second_chip = f"CHIP-1293-TX-B-{uuid.uuid4().hex[:8]}"

    # First INSERT (in its own transaction) lands and is fetchable.
    executor.execute_sql(_INSERT_ANIMAL_SQL, [first_chip, "Seed", "CANINA", "H"])

    # Now open a transaction, insert the second animal successfully,
    # then try to insert ANOTHER row with the same nchip as the seed.
    # The duplicate INSERT must raise UniqueViolationError; the
    # transaction must roll back, including the otherwise-valid
    # second_chip row.
    with pytest.raises(UniqueViolationError):
        with executor.transaction() as txn:
            txn.execute_sql(_INSERT_ANIMAL_SQL, [second_chip, "Will Rollback", "CANINA", "H"])
            # This second insert violates the nchip UNIQUE constraint.
            txn.execute_sql(_INSERT_ANIMAL_SQL, [first_chip, "Duplicate", "CANINA", "H"])

    # The transaction rolled back: second_chip was never committed.
    rows = executor.execute_sql(
        "SELECT nchip FROM animales WHERE nchip = $1",
        [second_chip],
    )
    assert rows == [], (
        "transaction() must roll back the whole unit of work on a "
        "UniqueViolationError — the sibling second_chip row must not survive"
    )

    # Sanity check: the first_chip seed row (committed before the
    # transaction opened) is still there.
    seed_rows = executor.execute_sql(
        "SELECT nchip FROM animales WHERE nchip = $1",
        [first_chip],
    )
    assert len(seed_rows) == 1
