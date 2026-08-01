"""Session-scoped Postgres fixture for integration tests (issue #329).

Provides an ephemeral schema with the full domain schema provisioned, so
every exported query function from ``app/modules/*/queries.py`` can be
executed against a real Postgres engine.

CI supplies ``APAP_TEST_POSTGRES_DSN`` via the service container.
The job MUST NOT silently skip when the DSN is absent.
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

_DSN_ENV = "APAP_TEST_POSTGRES_DSN"

# Full ordered list of domain schema statements needed for integration tests.
# Mirrors ensure_domain_schema() ordering (respects FK dependencies).
_DOMAIN_SQL_STATEMENTS = (
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


class _EphemeralPostgres:
    """Manages an ephemeral Postgres schema for integration tests."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema = f"int_test_{uuid.uuid4().hex[:12]}"
        self._provisioned = False
        self._provision()

    def _provision(self) -> None:
        """Create the ephemeral schema and provision all domain tables."""
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self._schema))
            )
            # Set search_path for the schema
            conn.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema))
            )
            for statement in _DOMAIN_SQL_STATEMENTS:
                # Each statement is a multi-statement SQL string; execute them
                # one by one. Skip empty strings.
                for line in statement.strip().split(";"):
                    trimmed = line.strip()
                    if trimmed:
                        conn.execute(sql.SQL(trimmed))
            conn.commit()
        self._provisioned = True

    def teardown(self) -> None:
        """Drop the ephemeral schema."""
        if not self._provisioned:
            return
        try:
            with psycopg.connect(self._dsn) as conn:
                conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(self._schema)
                    )
                )
                conn.commit()
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
