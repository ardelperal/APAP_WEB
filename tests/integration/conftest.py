"""Session-scoped Postgres fixture for integration tests (issue #329).

Provides an ephemeral schema with the full domain schema provisioned, so
every exported query function from ``app/modules/*/queries.py`` can be
executed against a real Postgres engine.

CI supplies ``APAP_TEST_POSTGRES_DSN`` via the service container.
The job MUST NOT silently skip when the DSN is absent.

catalogos_* CREATE TABLE statements are inlined here (issue #329 follow-up:
#379 re-applied the conftest without these, so the FK from ``contratos``
to ``catalogos_tipos_contrato`` failed on a fresh service container and
poisoned the rest of the transaction). Keeping them inline (rather than a
new ``app/core/domain_catalogos.py``) preserves the conftest's "stdlib-only,
no InsForge coupling" property and matches the close-scope fix.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

# Re-export the domain SQL constants so the fixture can provision
# all tables without importing InsForgeClient (the integration tests
# use raw psycopg, not InsForgeClient).
from app.core.domain_adopciones import ADOPCIONES_CREATE_TABLE_SQL
from app.core.domain_animales import ANIMALS_CREATE_TABLE_SQL
from app.core.domain_casas_acogida import CASAS_ACOGIDA_CREATE_TABLE_SQL
from app.core.domain_cesiones import CESIONES_PROPIETARIO_CREATE_TABLE_SQL
from app.core.domain_contracts import CONTRATOS_CREATE_TABLE_SQL
from app.core.domain_entradas import (
    ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL,
    ENTRADAS_CREATE_TABLE_SQL,
)
from app.core.domain_foster import (
    ACOGIDAS_ADD_CASA_FK_SQL,
    ACOGIDAS_CREATE_TABLE_SQL,
    FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL,
    FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL,
)
from app.core.domain_lifecycle import (
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_CURRENT_STATE_STATE_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL,
)
from app.core.domain_materiales import (
    ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL,
    ESTANCIA_MATERIALES_CREATE_TABLE_SQL,
    MATERIALES_CREATE_TABLE_SQL,
)
from app.core.domain_salud import ACTUACION_SANITARIA_CREATE_TABLE_SQL
from app.core.domain_voluntarios import (
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
)

# catalogos_* CREATE TABLE statements (issue #329 follow-up).
# Schemas verified 2026-08-01 against the InsForge project's underlying
# Postgres via `insforge.get-table-schema` MCP. The integration tests use raw
# psycopg against the service container — these CREATE TABLE IF NOT EXISTS
# statements are the only thing needed to make the ephemeral schema match
# the InsForge domain + catalogos layout.
_CATALOGOS_MOTIVOS_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_motivos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    especie TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_motivos_natural_key
    ON catalogos_motivos (codigo, especie);
"""

_CATALOGOS_ORIGENES_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_origenes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_origenes_codigo_key
    ON catalogos_origenes (codigo);
"""

_CATALOGOS_PERIODICIDAD_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_periodicidad (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    periodicidad_meses INTEGER NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_periodicidad_codigo_key
    ON catalogos_periodicidad (codigo);
"""

_CATALOGOS_PRUEBAS_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_pruebas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    especie TEXT NOT NULL,
    observaciones TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_pruebas_natural_key
    ON catalogos_pruebas (codigo, especie);
"""

_CATALOGOS_TIPOS_CONTRATO_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS catalogos_tipos_contrato (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    codigo TEXT NOT NULL,
    nombre TEXT NOT NULL,
    iniciales TEXT,
    descripcion TEXT,
    tabla_legacy TEXT,
    campo_legacy TEXT,
    activo BOOLEAN NOT NULL DEFAULT true,
    orden INTEGER,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS catalogos_tipos_contrato_codigo_key
    ON catalogos_tipos_contrato (codigo);
"""

_DSN_ENV = "APAP_TEST_POSTGRES_DSN"

# Full ordered list of schema statements needed for integration tests.
# Order respects FK dependencies: catalogos_* first (no FKs of their own,
# but referenced by contratos), then the existing domain statements.
_DOMAIN_SQL_STATEMENTS = (
    _CATALOGOS_MOTIVOS_CREATE_TABLE_SQL,
    _CATALOGOS_ORIGENES_CREATE_TABLE_SQL,
    _CATALOGOS_PERIODICIDAD_CREATE_TABLE_SQL,
    _CATALOGOS_PRUEBAS_CREATE_TABLE_SQL,
    _CATALOGOS_TIPOS_CONTRATO_CREATE_TABLE_SQL,
    ANIMALS_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    ENTRADAS_CREATE_TABLE_SQL,
    ENTRADAS_BATCH_STAGING_CREATE_TABLE_SQL,
    CASAS_ACOGIDA_CREATE_TABLE_SQL,
    ACOGIDAS_CREATE_TABLE_SQL,
    ACOGIDAS_ADD_CASA_FK_SQL,
    FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL,
    FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL,
    ADOPCIONES_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CREATE_TABLE_SQL,
    ANIMAL_LIFECYCLE_EVENTS_ANIMAL_TIMESTAMP_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_CAUSED_BY_INDEX_SQL,
    ANIMAL_CURRENT_STATE_CREATE_TABLE_SQL,
    ANIMAL_CURRENT_STATE_STATE_INDEX_SQL,
    CESIONES_PROPIETARIO_CREATE_TABLE_SQL,
    CONTRATOS_CREATE_TABLE_SQL,
    ACTUACION_SANITARIA_CREATE_TABLE_SQL,
    MATERIALES_CREATE_TABLE_SQL,
    ESTANCIA_MATERIALES_CREATE_TABLE_SQL,
    ESTANCIA_MATERIALES_ACTIVE_UNIQUE_INDEX_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_FUNCTION_SQL,
    ANIMAL_LIFECYCLE_EVENTS_DROP_APPEND_ONLY_TRIGGER_SQL,
    ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL,
)


def _require_postgres_dsn() -> str:
    """Return the DSN or fail with a hard error (not skip).

    The CI integration job MUST NOT silently skip when the DSN is absent.
    Locally, an explicit failure tells the operator to set the env var.
    """
    dsn = os.environ.get(_DSN_ENV)
    if not dsn:
        pytest.fail(
            f"Integration tests require PostgreSQL. Set {_DSN_ENV} to a "
            "test database DSN (e.g. postgresql://postgres@127.0.0.1:5432/apap_test). "
            "CI supplies this via the postgres service container."
        )
    return dsn


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split a multi-statement SQL string on outer semicolons.

    Respects PostgreSQL dollar-quoted blocks (``$$ ... $$`` and
    ``$tag$ ... $tag$``) and single-quoted string literals (with
    ``''`` as the escape). A naive ``split(';')`` breaks on the
    semicolons inside ``CREATE FUNCTION ... AS $$ ... $$ BEGIN ...
    'foo; bar' ... END; $$ LANGUAGE plpgsql`` bodies, so this
    splitter walks character-by-character and only emits a split at
    semicolons that are outside any quoted region.
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql_text)
    in_single = False
    dollar_tag: str | None = None  # the open tag (e.g. "$$" or "$func$") if inside one

    while i < n:
        ch = sql_text[i]

        # Inside a single-quoted string: only '' (escaped quote) ends it.
        if in_single:
            buf.append(ch)
            if ch == "'":
                if i + 1 < n and sql_text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue

        # Inside a dollar-quoted block: only the matching $tag$ ends it.
        if dollar_tag is not None:
            buf.append(ch)
            if ch == "$" and sql_text[i : i + len(dollar_tag)] == dollar_tag:
                # Append the rest of the tag (we already appended the leading '$').
                buf.extend(dollar_tag[1:])
                i += len(dollar_tag)
                dollar_tag = None
                continue
            i += 1
            continue

        # Generic handling outside any quoted region.
        if ch == "'":
            buf.append(ch)
            in_single = True
            i += 1
            continue

        if ch == "$":
            # Try to match a dollar-quote tag: $$, $tag$, $tag123$
            j = i + 1
            while j < n and (sql_text[j].isalnum() or sql_text[j] == "_"):
                j += 1
            if j < n and sql_text[j] == "$":
                dollar_tag = sql_text[i : j + 1]
                buf.append(dollar_tag)
                i = j + 1
                continue
            # Not a dollar-quote; fall through and treat as a literal char.

        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _run_statements(
    conn: psycopg.Connection, statements: tuple[str, ...]
) -> None:
    """Execute every (multi-)statement from ``statements`` against ``conn``.

    Each entry is run via a separate ``execute()`` call so the
    ``conn.autocommit=True`` setting (set by the caller) commits each
    statement independently. A failure surfaces the offending SQL
    immediately instead of poisoning the rest of the loop.
    """
    for raw in statements:
        for stmt in _split_sql_statements(raw):
            conn.execute(sql.SQL(stmt))


@pytest.fixture(scope="session")
def ephemeral_postgres() -> Iterator[_EphemeralPostgres]:
    """Session-scoped ephemeral Postgres schema with full domain schema.

    Creates a unique schema per test session, provisions all domain tables,
    and tears it down on cleanup. The same schema is reused across all
    integration tests in the session.
    """
    dsn = _require_postgres_dsn()
    EphemeralPostgres = _EphemeralPostgres(dsn)
    yield EphemeralPostgres
    EphemeralPostgres.teardown()


@pytest.fixture(autouse=True)
def _truncate_between_tests(ephemeral_postgres: _EphemeralPostgres) -> None:
    """Wipe all data before each test for isolation under the session-scoped schema."""
    with ephemeral_postgres.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = %s
                AND tablename NOT LIKE 'pg_%%'
                """,
                (ephemeral_postgres.schema,),
            )
            tables = [row["tablename"] for row in cur.fetchall()]
            if tables:
                cur.execute(f"TRUNCATE TABLE {', '.join(tables)} CASCADE")


class _EphemeralPostgres:
    """Manages an ephemeral Postgres schema for integration tests."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema = f"int_test_{uuid.uuid4().hex[:12]}"
        self._provisioned = False
        self._provision()

    def _provision(self) -> None:
        """Create the ephemeral schema and provision all domain tables.

        Uses ``autocommit=True`` so each statement is its own transaction —
        a failure in one statement does not poison the connection for the
        rest of the loop. This means pytest reports the FIRST failing
        statement instead of every subsequent one complaining about the
        same ``[BAD]`` connection state.

        ``_run_statements`` further splits each multi-statement SQL
        constant on outer semicolons (respecting dollar-quoted blocks and
        single-quoted string literals), so the ``;`` inside a
        ``RAISE EXCEPTION 'foo; bar'`` does not break the body.
        """
        with psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self._schema))
            )
            conn.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema))
            )
            _run_statements(conn, _DOMAIN_SQL_STATEMENTS)
        self._provisioned = True

    def teardown(self) -> None:
        """Drop the ephemeral schema."""
        if not self._provisioned:
            return
        try:
            with psycopg.connect(self._dsn, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(self._schema)
                    )
                )
        except Exception:
            # Best-effort cleanup; don't fail if already gone
            pass

    @property
    def schema(self) -> str:
        """The ephemeral schema name."""
        return self._schema

    @property
    def dsn(self) -> str:
        """The Postgres DSN."""
        return self._dsn

    @contextmanager
    def connection(self) -> Iterator[Any]:
        """Context manager for a connection with search_path set to the
        ephemeral schema.
        """
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            conn.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema))
            )
            yield conn

    def execute(
        self, query: str, params: tuple[Any, ...] | list[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a query and return all rows as dicts."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return list(cur.fetchall())
