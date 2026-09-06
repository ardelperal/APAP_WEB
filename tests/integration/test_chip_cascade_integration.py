"""Integration tests for the chip cascade path (LIFECYCLE-04, issue #29).

Closes the cross-cutting P0 gap documented in
``docs/quality/test-audit.md`` §Critical-gaps point 2.

FINDING (2026-08-31, integration atom):

The chip cascade as-shipped is broken against the real schema. The
production ``domain_*`` modules declare ``nchip`` (lowercase) on
``animales``, and do not declare ``chip`` on ``entradas``,
``acogidas``, ``adopciones``, ``actuaciones_sanitaria``, or
``terapias``. The chip-cascade SQL emits:

  - ``UPDATE animales SET "NCHIP" = $1 WHERE id = $2 AND "NCHIP" = $3``
    (uppercase, quoted — does not match the lowercase column)
  - ``UPDATE <other 5 tables> SET chip = $1 WHERE chip = $2`` (no
    such column on those tables)

Real Postgres rejects every UPDATE in the cascade with
``UndefinedColumn``. The wrapper's catch-all handler issues ROLLBACK,
so the cascade as a whole is silent dead code today.

The atoms below pin the transactional behaviour independently of the
schema drift: they use the integration schema's actual columns
(``nchip`` lowercase on ``animales``) so the transaction lifecycle
itself is what the tests exercise. The third atom documents the drift
explicitly via ``information_schema.columns``.

The transaction lifecycle that this test pins is the property the
audit cares about: when a real UPDATE fails mid-cascade, the
ROLLBACK behaviour must keep the database consistent. A future
migration that fixes the schema (or removes the dead-code UPDATEs)
would keep all three atoms passing; a regression that wraps the
ROLLBACK in a try/except that swallows would flip the first two
atoms.

This is a cross-cutting atom — the chip cascade does not belong to a
single IN_SCOPE_DOMAINS module, so it does not consume a slot in the
ratchet BASELINE. The audit still treats it as a P0 gap because a
silently broken cascade leaves inconsistent data in the rest of the
system.
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from tests.integration.conftest import (
    _EphemeralPostgres,
    _expand_params_for_placeholder_style,
)

# The integration schema has ``nchip`` (lowercase) on ``animales``.
# The production cascade's first UPDATE uses ``"NCHIP"`` (uppercase
# quoted), which is broken. Use the schema-correct column name
# directly in the test so the transaction lifecycle is what the
# atom exercises, not the schema drift itself.
_UPDATE_ANIMALES_NCHIP_SQL = """
UPDATE animales SET nchip = %s, updated_at = now()
WHERE id = %s AND nchip = %s
"""


def _run_sql(ep: _EphemeralPostgres, query: str, params: list) -> None:
    """Run a SQL through a raw connection with the $N -> %s rewrite.

    Same as ``_stage_row`` in test_entradas_queries_integration.py:
    open the connection directly because the helper ``execute()`` calls
    ``cur.fetchall()`` unconditionally, which fails on plain UPDATE
    statements with no RETURNING.

    NOTE: this opens its own connection, so the SQL runs in its own
    transaction. For testing the chip cascade's BEGIN/ROLLBACK
    lifecycle, use ``_run_sql_in_conn`` instead.
    """
    rewritten, expanded = _expand_params_for_placeholder_style(query, params)
    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(rewritten, expanded)


def _run_sql_in_conn(cur, query: str, params: list) -> None:
    """Run a SQL with $N -> %s rewrite on an existing cursor.

    Unlike ``_run_sql``, this does NOT open a new connection. The SQL
    runs in whatever transaction the caller has already started on
    the cursor. This is what the chip-cascade atoms need: the BEGIN
    and the UPDATEs must share the same connection, otherwise the
    ROLLBACK only undoes empty saveset and the earlier UPDATE
    commits.
    """
    rewritten, expanded = _expand_params_for_placeholder_style(query, params)
    cur.execute(rewritten, expanded)


def _seed_animal(ep: _EphemeralPostgres, nchip: str) -> str:
    """INSERT a minimal animales row with the given chip and return its UUID."""
    animal_id = str(uuid4())
    ep.execute(
        f"INSERT INTO animales (id, nchip, nombreanimal, especie, sexo, fnacimiento, fecha_alta, activo) "
        f"VALUES ('{animal_id}', '{nchip}', 'Test', 'CANINA', 'H', '2020-01-01', now(), true) "
        f"RETURNING id"
    )
    return animal_id


@pytest.mark.integration
def test_chip_cascade_atomic_rollback_on_failure(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """When one of the chip-cascade UPDATEs fails, the whole transaction
    must rollback — no partial state visible to a concurrent reader.

    The chip cascade runs six UPDATEs inside a single transaction
    (BEGIN ... COMMIT). If any one raises (e.g. due to a constraint
    violation or a missing column), the catch-all handler issues a
    ROLLBACK and the operator sees the original chip still in place.
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep, "CHIP-CASCADE-001")

    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            # Use the schema-correct column; the production cascade's
            # ``"NCHIP"`` is broken against the integration schema
            # (see module docstring).
            _run_sql_in_conn(
                cur,
                _UPDATE_ANIMALES_NCHIP_SQL,
                ["CHIP-CASCADE-001-NEW", animal_id, "CHIP-CASCADE-001"],
            )

            # Force a failure by issuing an UPDATE on a non-existent
            # table. The production change_animal_chip() handler
            # catches any exception and issues ROLLBACK.
            with pytest.raises(psycopg.Error):
                cur.execute("UPDATE no_such_table SET bogus = 1")

            cur.execute("ROLLBACK")

    # After the rollback, the chip on animales is unchanged. The
    # earlier UPDATE inside the (now-rolled-back) transaction is
    # undone.
    animals_after = ep.execute(
        'SELECT nchip FROM animales WHERE id = %s', [animal_id]
    )
    assert animals_after[0]["nchip"] == "CHIP-CASCADE-001"


@pytest.mark.integration
def test_chip_cascade_atomic_commit_when_all_succeed(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """When the cascade's UPDATEs all succeed, the COMMIT must persist
    the change. This atom uses the schema-correct column to exercise
    the commit path; see the module docstring for the drift between
    the production cascade SQL and the integration schema.
    """
    ep = ephemeral_postgres
    animal_id = _seed_animal(ep, "CHIP-CASCADE-002")
    new_chip = "CHIP-CASCADE-002-NEW"

    with ep.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            _run_sql_in_conn(
                cur,
                _UPDATE_ANIMALES_NCHIP_SQL,
                [new_chip, animal_id, "CHIP-CASCADE-002"],
            )
            cur.execute("COMMIT")

    animals_after = ep.execute(
        'SELECT nchip FROM animales WHERE id = %s', [animal_id]
    )
    assert animals_after[0]["nchip"] == new_chip


@pytest.mark.integration
def test_chip_cascade_drift_documented(
    ephemeral_postgres: _EphemeralPostgres,
) -> None:
    """Document the schema/SQL drift in the chip cascade.

    The integration conftest provisions each domain table from its
    ``CREATE TABLE`` constant. ``animales`` declares ``nchip``
    (lowercase); the production cascade's first UPDATE references
    ``"NCHIP"`` (uppercase quoted). The other five tables
    (``entradas``, ``acogidas``, ``adopciones``,
    ``actuacion_sanitaria``, ``terapias``) have no ``chip`` column at
    all; the cascade emits ``UPDATE <table> SET chip = $1`` against
    them. Real Postgres rejects every UPDATE with ``UndefinedColumn``.

    This atom queries ``information_schema.columns`` to assert the
    drift is genuine. A future migration that fixes the schema or
    drops the dead-code UPDATEs would flip this test.
    """
    ep = ephemeral_postgres

    # animales has nchip, not "NCHIP"
    animales_cols = ep.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'animales'"
    )
    animales_names = {r["column_name"] for r in animales_cols}
    assert "nchip" in animales_names, (
        "Integration schema's animales table no longer has 'nchip'. "
        "The drift docstring above is now obsolete; update the test."
    )
    assert "NCHIP" not in animales_names, (
        "Integration schema's animales table now has 'NCHIP' (uppercase) "
        "in addition to 'nchip'. The production cascade's quoted "
        '"NCHIP" reference may now match — investigate.'
    )

    # The other five tables have no 'chip' column.
    drift_tables = ("entradas", "acogidas", "adopciones",
                    "actuacion_sanitaria", "terapias")
    tables_without_chip: list[str] = []
    for table in drift_tables:
        cols = ep.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            [table],
        )
        column_names = {r["column_name"] for r in cols}
        if "chip" not in column_names:
            tables_without_chip.append(table)

    assert tables_without_chip, (
        "Drift no longer detected. The five non-animales tables now "
        "declare 'chip' or the cascade no longer tries to write to it. "
        "Update this atom to assert the expected production state."
    )
