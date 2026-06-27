"""Sandbox test for migration 004 — drop CHECK on usuarios_autorizados.rol.

Runs against a real PostgreSQL (the migration is DDL and verification
needs ``pg_constraint`` introspection). Gates:

  - Skip if ``APAP_TEST_PG_DSN`` is not set.
  - Skip if ``psycopg`` is not installed (``importorskip``).

This matches the SPEC 07 (TOCTOU) policy: the test must be real (not
``assert True``) and skip cleanly without PostgreSQL. The PR
description carries the operator-driven post-deploy verification
steps for staging, where dysflow does not reach PostgreSQL.

Reference: openspec/changes/hardening-2026-q2/specs/02-rule-4-ddl/spec.md (REQ-3)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")  # noqa: F401 — skip if not installed


_MIGRATION_SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "core"
    / "migration"
    / "sql"
    / "004_drop_rol_check.sql"
)
_TABLE_NAME = "test_migration_004_usuarios_autorizados"


def _pg_dsn() -> str | None:
    return os.environ.get("APAP_TEST_PG_DSN")


@pytest.fixture
def pg_conn():
    """Yield a real psycopg connection, or skip if no DSN."""
    dsn = _pg_dsn()
    if not dsn:
        pytest.skip(
            "T-2.9 sandbox test requires PostgreSQL; "
            "set APAP_TEST_PG_DSN to a libpq-style DSN to run it."
        )
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def isolated_table(pg_conn):
    """Create a hermetic ``usuarios_autorizados`` clone WITH the CHECK.

    Mirrors the staging pre-PR state. Drops any leftover from a
    previous run on entry and on exit.
    """
    pg_conn.execute(f"DROP TABLE IF EXISTS {_TABLE_NAME} CASCADE")
    pg_conn.execute(
        f"""
        CREATE TABLE {_TABLE_NAME} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            rol TEXT NOT NULL
                CHECK (rol IN ('developer', 'admin', 'key_user', 'reader')),
            anadido_por UUID,
            activo BOOLEAN NOT NULL DEFAULT true,
            fecha_alta TIMESTAMP NOT NULL DEFAULT now()
        )
        """
    )
    pg_conn.commit()
    try:
        yield _TABLE_NAME
    finally:
        pg_conn.execute(f"DROP TABLE IF EXISTS {_TABLE_NAME} CASCADE")
        pg_conn.commit()


def _check_constraints(pg_conn, table_name: str) -> list[str]:
    """Return the names of CHECK constraints on the given table."""
    rows = pg_conn.execute(
        """
        SELECT conname FROM pg_constraint
        WHERE conrelid = %s::regclass AND contype = 'c'
        """,
        (table_name,),
    ).fetchall()
    return [row[0] for row in rows]


def _patched_migration_sql(table_name: str) -> str:
    """Return the migration SQL with the table name patched for the sandbox."""
    original = _MIGRATION_SQL_PATH.read_text(encoding="utf-8")
    return original.replace("usuarios_autorizados", table_name)


def test_migration_drops_check_constraint(isolated_table, pg_conn) -> None:
    """The migration SQL removes the CHECK constraint on the ``rol`` column."""
    pre = _check_constraints(pg_conn, isolated_table)
    assert pre, f"Expected a CHECK on {isolated_table}; got none"
    assert any("rol" in name for name in pre), (
        f"Expected a CHECK on rol; got {pre}"
    )

    pg_conn.execute(_patched_migration_sql(isolated_table))
    pg_conn.commit()

    post = _check_constraints(pg_conn, isolated_table)
    assert all("rol" not in name for name in post), (
        f"Expected rol CHECK to be gone; got {post}"
    )


def test_migration_is_idempotent(isolated_table, pg_conn) -> None:
    """Running the migration twice in a row does not raise."""
    sql = _patched_migration_sql(isolated_table)
    pg_conn.execute(sql)
    pg_conn.commit()
    pg_conn.execute(sql)
    pg_conn.commit()


def test_migration_noop_when_no_check(isolated_table, pg_conn) -> None:
    """If the CHECK is already absent, the migration is a clean no-op."""
    pg_conn.execute(
        f"ALTER TABLE {isolated_table} "
        f"DROP CONSTRAINT IF EXISTS {isolated_table}_rol_check"
    )
    pg_conn.commit()
    pg_conn.execute(_patched_migration_sql(isolated_table))
    pg_conn.commit()


def test_migration_allows_any_rol_after_drop(isolated_table, pg_conn) -> None:
    """After the CHECK is gone, the DB no longer enforces rol validity.

    App-level validation in ``add_authorized_user`` (against
    ``VALID_ROLES``) becomes the sole gate — the Rule 4 invariant
    the slice was designed to establish.
    """
    pg_conn.execute(_patched_migration_sql(isolated_table))
    pg_conn.commit()

    pg_conn.execute(
        f"INSERT INTO {isolated_table} (email, rol) VALUES (%s, %s)",
        ("future-role@example.com", "volunteer"),
    )
    pg_conn.commit()

    rows = pg_conn.execute(
        f"SELECT rol FROM {isolated_table} WHERE email = %s",
        ("future-role@example.com",),
    ).fetchall()
    assert rows and rows[0][0] == "volunteer"
