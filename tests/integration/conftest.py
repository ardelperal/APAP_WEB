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
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

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
from app.core.domain_terapias import (
    RECOMENDACIONES_CREATE_TABLE_SQL,
    TERAPIAS_CREATE_TABLE_SQL,
)
from app.core.domain_voluntarios import (
    ROLES_VOLUNTARIO_CREATE_TABLE_SQL,
    VOLUNTARIOS_CREATE_TABLE_SQL,
)

_DOLLAR_PLACEHOLDER = re.compile(r"\$(\d+)")


def _to_client_placeholder_style(query: str) -> str:
    """Rewrite ``$N`` placeholders as ``%s`` for psycopg3 v3.3.4's client.

    The query builders in ``app/modules/*/queries.py`` use ``$N``
    placeholders (native Postgres extended-protocol style). psycopg3
    v3.3.4's default ``ClientCursor`` runs every ``execute()`` through
    ``PostgresQuery.convert()`` whose regex (in
    ``psycopg/_queries.py::_re_placeholder``) only matches ``%s`` /
    ``%(name)s`` — so a query that only has ``$N`` is parsed as having
    zero placeholders and the bind check raises
    ``the query has 0 placeholders but N parameters were passed``.

    Translating to ``%s`` is invisible to the server: the C extension's
    ``_query2pg_client`` rewrites ``%s`` to ``$N`` for the wire protocol
    before sending, and Postgres parses the ``$N`` natively. So the
    statement that reaches the server is byte-identical to what
    ``queries.py`` wrote.

    We do this translation at the test-boundary in ``execute`` (NOT in
    ``queries.py``) so that:

    - The production code path (``InsForgeClient.execute_sql`` — HTTP
      to the InsForge API) is untouched. InsForge's server receives
      ``$N`` placeholders, which it binds natively.
    - The integration tests run against any Postgres (not just
      InsForge): psycopg3 is server-agnostic and translates ``%s`` to
      ``$N`` automatically.

    Alternative architectures that we tried and rejected:

    - ``ServerCursor`` (bypasses client-side parse, lets the server
      bind ``$N`` natively): psycopg3 v3.3.4's ServerCursor only
      supports ``SELECT`` statements — it sends
      ``DECLARE name CURSOR FOR <query>`` which the server rejects for
      ``INSERT`` / ``UPDATE`` / ``DELETE`` with
      ``syntax error at or near "INSERT"``. The integration tests
      execute all four statement types, so ServerCursor is not viable.
    """
    if "$" in query:
        return _DOLLAR_PLACEHOLDER.sub("%s", query)
    return query


def _expand_params_for_placeholder_style(
    query: str, params: list[Any]
) -> tuple[str, list[Any]]:
    """Rewrite ``$N`` → ``%s`` and pad ``params`` to match each distinct
    placeholder occurrence.

    psycopg3 v3.3.4's ``ClientCursor`` client-side parser counts every
    ``%s`` as a distinct bind slot, so a production query that
    references ``$1`` twice (perfectly valid in Postgres' extended
    protocol) ends up with two ``%s`` placeholders and demands two bind
    values. We track each distinct ``$N`` occurrence and emit one param
    per occurrence. Where the SQL references an ``$N`` higher than
    ``len(params)`` (e.g. server-managed columns like ``updated_at`` that
    do not appear in the test params), we pad with ``None`` so the bind
    count matches the placeholder count.
    """
    if not params:
        return _to_client_placeholder_style(query), params
    indices: list[int] = []

    def _sub(match: re.Match[str]) -> str:
        indices.append(int(match.group(1)))
        return "%s"

    rewritten = _DOLLAR_PLACEHOLDER.sub(_sub, query)
    if not indices:
        return rewritten, params
    expanded: list[Any] = []
    for n in indices:
        if 1 <= n <= len(params):
            expanded.append(params[n - 1])
        else:
            expanded.append(None)
    return rewritten, expanded

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
    TERAPIAS_CREATE_TABLE_SQL,
    RECOMENDACIONES_CREATE_TABLE_SQL,
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


@pytest.fixture
def postgres_dsn() -> str:
    """Expose the APAP_TEST_POSTGRES_DSN env var for tests that need
    to build their own psycopg connection (rather than going through
    the integration conftest's ``ephemeral_postgres`` wrapper).

    M0 of the self-host-backend-coolify openspec (issue #641).
    """
    return os.environ["APAP_TEST_POSTGRES_DSN"]


@pytest.fixture
def schema_postgres_dsn(ephemeral_postgres) -> str:
    """DSN that points at the same database the ephemeral schema lives in.

    Tests that need to build their own psycopg connection (the
    ``LocalPostgresExecutor`` does this) should use this DSN rather
    than the global ``APAP_TEST_POSTGRES_DSN`` because the ephemeral
    schema (``ephemeral_postgres.schema``) only exists on the same
    Postgres instance the integration conftest provisioned.

    The DSN is identical to ``APAP_TEST_POSTGRES_DSN`` but documented
    here as a separate fixture so tests that need the schema can
    request it explicitly.

    M0 of the self-host-backend-coolify openspec (issue #641).
    """
    return os.environ["APAP_TEST_POSTGRES_DSN"]


@pytest.fixture(autouse=True)
def _truncate_between_tests(ephemeral_postgres: _EphemeralPostgres) -> None:
    """Wipe all data before each test for isolation under the session-scoped schema."""
    schema = ephemeral_postgres.schema
    with ephemeral_postgres.connection() as conn:
        with conn.cursor() as cur:
            # ``left(tablename, 2) <> 'pg'`` excludes the Postgres system
            # tables (``pg_class``, ``pg_attribute``, ...). The schema name
            # is a UUID we generate in ``__init__`` so it is safe to
            # interpolate directly into the SQL string (no user input
            # involved). ``cur.execute(query)`` with no params takes the
            # simple-query protocol path, which the cursor sends as a raw
            # Parse message to the server and the server handles ``$N``
            # natively — bypassing psycopg3's client-side placeholder
            # parser that only counts ``%`` style placeholders.
            cur.execute(
                f"""
                SELECT tablename FROM pg_tables
                WHERE schemaname = '{schema}'
                AND left(tablename, 2) <> 'pg'
                """
            )
            tables = [row["tablename"] for row in cur.fetchall()]
            if tables:
                cur.execute(f"TRUNCATE TABLE {', '.join(tables)} CASCADE")





@pytest.fixture
def self_host_schema(ephemeral_postgres):
    """Extend the ephemeral Postgres schema with the self-host auth tables.

    Creates ``usuarios_autorizados`` (not in the domain provisioning)
    and applies migrations 007 (add password_hash, email_verified_at,
    failed_attempts) and 008 (create ``magic_link_tokens``). Tests that
    need classic password auth or magic-link tokens depend on this
    fixture instead of the bare ``ephemeral_postgres``.

    M1 of the self-host-backend-coolify openspec (issue #641).
    """
    from pathlib import Path
    from app.core.adapters.insforge.auth_insforge_queries import (
        CREATE_TABLE_SQL as USUARIOS_AUTORIZADOS_CREATE_SQL,
    )

    # Create the auth core table first (it is not in the domain
    # provisioning). Then apply the M1 migrations on top.
    with ephemeral_postgres.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(USUARIOS_AUTORIZADOS_CREATE_SQL)

    migrations_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "app" / "core" / "migration" / "sql"
    )
    for migration_name in (
        "007_add_password_hash.sql",
        "008_create_magic_link_tokens.sql",
    ):
        sql_text = (migrations_dir / migration_name).read_text(encoding="utf-8")
        with ephemeral_postgres.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_text)
    yield ephemeral_postgres

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
        ephemeral schema. Uses psycopg3's default ``ClientCursor``
        (which is the only cursor type that supports INSERT/UPDATE/DELETE
        in addition to SELECT — see ``_to_client_placeholder_style``
        for why we cannot use ``ServerCursor``).
        """
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            conn.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(self._schema))
            )
            yield conn

    def execute(
        self, query: str, params: tuple[Any, ...] | list[Any] | None = None
        ) -> list[dict[str, Any]]:
        """Execute a query and return all rows as dicts.

        ``$N`` placeholders in the query are rewritten to ``%s`` at the
        test boundary (``_to_client_placeholder_style``) so psycopg3
        v3.3.4's ``ClientCursor`` parses the bind count correctly. The
        server still receives ``$N`` SQL because psycopg3's C extension
        re-number ``%s`` to ``$N`` for the wire protocol.

        Because each ``$N`` becomes its own ``%s`` (no dedup), the
        substituted query may have more placeholders than the original
        ``$N`` count when the production SQL legitimately references
        the same ``$N`` twice (e.g. ``_INSERT_ADOPCION_SQL`` joins a
        CTE row to the same ``$1`` in the main INSERT). We therefore
        expand ``params`` to one entry per occurrence so psycopg3's
        bind-count check passes; the wire protocol still binds every
        duplicated slot to the same value.
        """
        if params is None:
            params = []
        else:
            params = list(params)
        rewritten_query, expanded_params = _expand_params_for_placeholder_style(
            query, params
        )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(rewritten_query, expanded_params)
                return list(cur.fetchall())

    def execute_sql(
        self, query: str, params: tuple[Any, ...] | list[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Alias of ``execute`` matching the SqlExecutor Protocol.

        The integration conftest exposes ``execute`` (its own
        internal name); production code (and our local adapters)
        use the SqlExecutor Protocol which calls ``execute_sql``.
        Both names do the same thing — the alias keeps the
        production code calling the canonical name without the
        conftest needing a different fixture signature.

        INSERT/UPDATE/DELETE return no rows so we wrap fetchall in
        a try/except for ProgrammingError. The Protocol's
        ``list[dict]`` return type allows empty lists.
        """
        rewritten_query, expanded_params = _expand_params_for_placeholder_style(
            query, [] if params is None else list(params)
        )
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(rewritten_query, expanded_params)
                try:
                    return list(cur.fetchall())
                except psycopg.ProgrammingError:
                    return []
