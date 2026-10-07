"""Integration tests for ``LocalPostgresExecutor.transaction()`` (issue #913, A-01).

Today ``LocalPostgresExecutor.execute_sql`` opens a fresh connection and
commits per call, so no multi-statement write is atomic (finding A-01 of
audit #911). These tests pin the new ``transaction()`` unit-of-work: one
connection, COMMIT on clean exit, ROLLBACK on any exception, the connection
always closed, and no nested transactions (no savepoints).

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): each atom builds its own state via unique ``nchip``
  values and the autouse ``_truncate_between_tests`` fixture.
- Rule 4 (no humo): assertions on real persisted row counts, not
  absence-of-error.
- Rule 8 (no production mutation): tests run against the session-scoped
  ephemeral Postgres schema; no real LocalBackend touched.
"""

from __future__ import annotations

import pytest

from app.core.data_access import NestedTransactionError
from app.core.local_backend.db import LocalPostgresExecutor, QueryError

pytestmark = pytest.mark.integration

_INSERT_ANIMAL_SQL = (
    "INSERT INTO animales (nchip, nombreanimal, especie, sexo, fnacimiento) "
    "VALUES ($1, $2, 'CANINA', 'H', '2020-01-01')"
)


def _make_executor(ephemeral_postgres) -> LocalPostgresExecutor:
    return LocalPostgresExecutor(ephemeral_postgres.dsn, search_path=ephemeral_postgres.schema)


def _count_animales(ephemeral_postgres) -> int:
    rows = ephemeral_postgres.execute_sql("SELECT count(*) AS n FROM animales", [])
    return rows[0]["n"]


def test_transaction_rolls_back_all_statements_on_forced_exception(
    ephemeral_postgres,
):
    """Two INSERTs inside ``transaction()`` then a forced exception persist nothing."""
    executor = _make_executor(ephemeral_postgres)

    with pytest.raises(RuntimeError, match="forced failure"):
        with executor.transaction() as txn:
            txn.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-001", "Uno"])
            txn.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-002", "Dos"])
            raise RuntimeError("forced failure")

    assert _count_animales(ephemeral_postgres) == 0


def test_transaction_commits_all_statements_on_clean_exit(ephemeral_postgres):
    """Two INSERTs inside ``transaction()`` with no error both persist."""
    executor = _make_executor(ephemeral_postgres)

    with executor.transaction() as txn:
        txn.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-003", "Uno"])
        txn.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-004", "Dos"])

    assert _count_animales(ephemeral_postgres) == 2


def test_transaction_is_invisible_to_other_connections_until_commit(
    ephemeral_postgres,
):
    """A separate plain ``execute_sql`` (other connection) sees nothing mid-transaction."""
    executor = _make_executor(ephemeral_postgres)

    with executor.transaction() as txn:
        txn.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-005", "Uno"])
        # Uses a brand-new connection (ephemeral_postgres.execute_sql), not
        # the one held open by the transaction.
        assert _count_animales(ephemeral_postgres) == 0

    assert _count_animales(ephemeral_postgres) == 1


def test_transaction_translates_psycopg_error_and_rolls_back(ephemeral_postgres):
    """A UNIQUE violation inside the transaction raises QueryError and rolls back."""
    executor = _make_executor(ephemeral_postgres)

    with pytest.raises(QueryError):
        with executor.transaction() as txn:
            txn.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-006", "Uno"])
            txn.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-006", "Duplicado"])

    assert _count_animales(ephemeral_postgres) == 0


def test_nested_transaction_raises_without_savepoints(ephemeral_postgres):
    """Calling ``transaction()`` on the bound executor raises, no savepoints."""
    executor = _make_executor(ephemeral_postgres)

    with pytest.raises(NestedTransactionError):
        with executor.transaction() as txn:
            with txn.transaction():
                pass  # pragma: no cover - never reached


def test_plain_execute_sql_still_commits_per_call(ephemeral_postgres):
    """Plain ``execute_sql`` outside a transaction keeps its exact current
    behaviour: each call commits independently."""
    executor = _make_executor(ephemeral_postgres)

    executor.execute_sql(_INSERT_ANIMAL_SQL, ["CHIP-TXN-007", "Uno"])

    assert _count_animales(ephemeral_postgres) == 1


def test_transaction_translates_error_raised_by_commit(ephemeral_postgres) -> None:
    """A failure surfaced only at COMMIT (deferred constraint) is a ``QueryError``."""
    executor = _make_executor(ephemeral_postgres)

    with pytest.raises(QueryError):
        with executor.transaction() as tx:
            tx.execute_sql(
                "CREATE TEMP TABLE deferred_probe (id int, "
                "CONSTRAINT deferred_probe_uq UNIQUE (id) DEFERRABLE INITIALLY DEFERRED)"
            )
            tx.execute_sql("INSERT INTO deferred_probe (id) VALUES (1), (1)")
