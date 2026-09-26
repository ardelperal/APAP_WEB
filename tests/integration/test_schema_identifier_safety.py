"""Identifier safety for schema names reaching DDL (issue #920, finding A-08).

Both DDL sites that interpolate a caller-supplied schema name:

- ``app.core.schema_provisioning.provision_apap_schema`` (CREATE SCHEMA
  + SET search_path),
- ``app.core.local_backend.db.LocalPostgresExecutor._connect`` (SET
  search_path from ``Settings.local_db_schema``)

must render the name through ``psycopg.sql.Identifier`` so a name
containing a double quote is safely escaped (and re-reads identically)
instead of breaking the statement or letting the remainder of the value
escape the identifier. Proven against the real Postgres instance.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg import sql

from app.core.local_backend.db import LocalPostgresExecutor
from app.core.schema_provisioning import provision_apap_schema

pytestmark = pytest.mark.integration

# A double quote is the minimal breaking payload: with the pre-#920
# f-string the statement splits inside the identifier and Postgres
# rejects it, instead of creating a schema with this literal name.
HOSTILE_SCHEMA = 'evil"schema'


def _drop_schema(dsn: str, name: str) -> None:
    """Remove the test schema (both before and after each test)."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name))
        )


def test_provision_apap_schema_escapes_double_quote(postgres_dsn: str) -> None:
    _drop_schema(postgres_dsn, HOSTILE_SCHEMA)
    try:
        provision_apap_schema(postgres_dsn, HOSTILE_SCHEMA)

        with psycopg.connect(postgres_dsn) as conn:
            rows = conn.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname = %s",
                (HOSTILE_SCHEMA,),
            ).fetchall()

        assert len(rows) == 1, f"schema {HOSTILE_SCHEMA!r} was not created verbatim"
    finally:
        _drop_schema(postgres_dsn, HOSTILE_SCHEMA)


def test_provision_apap_schema_lands_tables_in_hostile_schema(postgres_dsn: str) -> None:
    _drop_schema(postgres_dsn, HOSTILE_SCHEMA)
    try:
        provision_apap_schema(postgres_dsn, HOSTILE_SCHEMA)

        with psycopg.connect(postgres_dsn) as conn:
            rows = conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s",
                (HOSTILE_SCHEMA,),
            ).fetchall()

        assert {row[0] for row in rows} >= {"animales", "usuarios_autorizados"}
    finally:
        _drop_schema(postgres_dsn, HOSTILE_SCHEMA)


def test_executor_search_path_escapes_double_quote(postgres_dsn: str) -> None:
    _drop_schema(postgres_dsn, HOSTILE_SCHEMA)
    try:
        with psycopg.connect(postgres_dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(HOSTILE_SCHEMA)
                )
            )

        executor = LocalPostgresExecutor(postgres_dsn, search_path=HOSTILE_SCHEMA)
        rows = executor.execute_sql("SELECT current_schema() AS schema")

        assert rows == [{"schema": HOSTILE_SCHEMA}]
    finally:
        _drop_schema(postgres_dsn, HOSTILE_SCHEMA)
