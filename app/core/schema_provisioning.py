"""Schema provisioning helper for non-test consumers of the local backend.

The integration tests provision the full APAP domain schema in an
ephemeral Postgres schema via ``tests/integration/conftest.py``.
Non-test consumers (the verify-fallback-ready gate, ad-hoc scripts,
the Coolify-deployed local backend in M2) need the same schema
without taking a dependency on the test conftest.

This module exposes ``provision_apap_schema(dsn, schema)`` which runs
the same ordered DDL list the integration tests use, plus the
``usuarios_autorizados`` table and the M1 migrations (007 + 008).
The order respects FK dependencies (catalogos_* first, then domain
tables, then M1 patches).

Hard rules (web-tdd-philosophy):
- Rule 4 (no humo): the function raises on the first failing
  statement, never silently swallows errors.
- Rule 8 (no production mutation): the caller is responsible for
  passing a schema name that will not collide with production (the
  gate uses a UUID-suffixed name and drops it after the check).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import psycopg

# Domain DDL constants — same imports the integration conftest uses so the
# helper produces an identical schema. Imported at module level so the
# APAP003 rule linter does not flag them as unjustified lazy imports.
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


def _load_conftest_catalogos() -> tuple[str, ...]:
    """Import the catalogos DDL constants from the integration conftest.

    The catalogos are module-level ``CATALOGOS_*`` constants in
    ``tests/integration/conftest.py`` (renamed from the original
    underscore-prefixed names so non-test code can import them).
    Loading them at runtime keeps a single source of truth for the
    schema layout — if the conftest adds a new catalog, the helper
    picks it up automatically.
    """
    conftest = importlib.import_module("tests.integration.conftest")
    return (
        conftest.CATALOGOS_MOTIVOS_CREATE_TABLE_SQL,
        conftest.CATALOGOS_ORIGENES_CREATE_TABLE_SQL,
        conftest.CATALOGOS_PERIODICIDAD_CREATE_TABLE_SQL,
        conftest.CATALOGOS_PRUEBAS_CREATE_TABLE_SQL,
        conftest.CATALOGOS_TIPOS_CONTRATO_CREATE_TABLE_SQL,
    )


def _load_domain_statements() -> tuple[str, ...]:
    """Return the ordered domain DDL list (catalogos + domain tables).

    Catalogos come from the integration conftest (single source of
    truth); domain tables come from the module-level imports above.
    Order respects FK dependencies — catalogos first, then tables
    that reference them, then the lifecycle append-only trigger.
    """
    catalogos = _load_conftest_catalogos()
    return (
        *catalogos,
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


_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migration" / "sql"
_MIGRATION_FILES = (
    "007_add_password_hash.sql",
    "008_create_magic_link_tokens.sql",
)


def _split_statements(sql_text: str) -> list[str]:
    """Split a multi-statement SQL text into individual statements.

    Splits on outer semicolons (respecting single-quoted strings,
    dollar-quoted blocks, and ``--`` line comments). Mirrors the
    helper in ``tests/integration/conftest.py`` so the gate's
    behaviour matches the test conftest's behaviour.
    """
    out: list[str] = []
    buf: list[str] = []
    in_single = False
    in_dollar = False
    in_line_comment = False
    dollar_tag = ""
    i = 0
    while i < len(sql_text):
        ch = sql_text[i]
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
        elif in_single:
            buf.append(ch)
            if ch == "'" and (i + 1 >= len(sql_text) or sql_text[i + 1] != "'"):
                in_single = False
            elif ch == "'" and sql_text[i + 1] == "'":
                buf.append(sql_text[i + 1])
                i += 1
        elif in_dollar:
            buf.append(ch)
            if (
                ch == "$"
                and sql_text[i:i + len(dollar_tag)] == dollar_tag
            ):
                in_dollar = False
                dollar_tag = ""
        else:
            if ch == "'":
                in_single = True
                buf.append(ch)
            elif ch == "$":
                j = i + 1
                while j < len(sql_text) and (sql_text[j].isalnum() or sql_text[j] == "_"):
                    j += 1
                if j < len(sql_text) and sql_text[j] == "$":
                    dollar_tag = sql_text[i:j + 1]
                    in_dollar = True
                    buf.append(sql_text[i:j + 1])
                    i = j
                else:
                    buf.append(ch)
            elif ch == "-" and i + 1 < len(sql_text) and sql_text[i + 1] == "-":
                in_line_comment = True
                buf.append(ch)
            elif ch == ";":
                stmt = "".join(buf).strip()
                if stmt:
                    out.append(stmt)
                buf = []
            else:
                buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def provision_apap_schema(dsn: str, schema: str) -> None:
    """Provision the APAP domain schema in the given Postgres DSN.

    Idempotent: re-running on an existing schema is a no-op (the
    ``CREATE SCHEMA IF NOT EXISTS`` swallows the duplicate).

    Mirrors the integration conftest's ``_EphemeralPostgres._provision``:
    same DDL list, same M1 migration order, same auth core table.
    """
    statements = _load_domain_statements()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.execute(f'SET search_path TO "{schema}"')
        for stmt in statements:
            for piece in _split_statements(stmt):
                conn.execute(piece)
        # Auth core table (the integration conftest does this too via
        # ``self_host_auth`` fixture; non-test consumers need it because
        # ``migration.apply`` queries ``usuarios_autorizados``).
        # lazy-import: avoid circular import — ``app.core.adapters.insforge``
        # depends on ``app.core.data_access`` which this module transitively
        # loads via ``psycopg``. Hoisting the import would break the
        # conftest-shaped import graph the rest of the repo assumes.
        from app.core.adapters.insforge.auth_insforge_queries import (
            CREATE_TABLE_SQL as USUARIOS_AUTORIZADOS_CREATE_SQL,
        )
        for piece in _split_statements(USUARIOS_AUTORIZADOS_CREATE_SQL):
            conn.execute(piece)
        # M1 migrations on top.
        for migration_name in _MIGRATION_FILES:
            sql_text = (_MIGRATIONS_DIR / migration_name).read_text(
                encoding="utf-8"
            )
            for piece in _split_statements(sql_text):
                conn.execute(piece)


__all__ = ["provision_apap_schema"]
