"""REQ-3: regresión PostgreSQL para el deactivate atómico de voluntarios.

Usa ``APAP_TEST_POSTGRES_DSN``; ``APAP_E2E_BASE_URL`` es solo una URL HTTP.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from app.modules.voluntarios import service as voluntarios_service

_POSTGRES_DSN_ENV = "APAP_TEST_POSTGRES_DSN"


def _require_postgres_dsn() -> str:
    dsn = os.environ.get(_POSTGRES_DSN_ENV)
    if not dsn:
        pytest.fail(
            "La regresión TOCTOU requiere PostgreSQL real; define "
            f"{_POSTGRES_DSN_ENV} con el DSN de una base de datos de pruebas. "
            "APAP_E2E_BASE_URL no sirve: es una URL HTTP, no un DSN."
        )
    return dsn


class _PostgresExecutor:
    def __init__(self, dsn: str, schema: str, barrier: Barrier | None = None) -> None:
        self._dsn = dsn
        self._schema = schema
        self._barrier = barrier

    def execute_sql(
        self,
        query: str,
        params: Sequence[Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self._barrier is not None:
            self._barrier.wait(timeout=10)

        psycopg_query = query.replace("$1", "%s")
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SET LOCAL search_path TO {}").format(
                        sql.Identifier(self._schema)
                    )
                )
                cursor.execute(psycopg_query, params)
                return list(cursor.fetchall())


@pytest.fixture
def postgres_voluntario() -> Iterator[tuple[str, str, str]]:
    dsn = _require_postgres_dsn()
    schema = f"toctou_{uuid4().hex}"
    voluntario_id = str(uuid4())

    with psycopg.connect(dsn) as connection:
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
        connection.execute(
            sql.SQL(
                """
                CREATE TABLE {}.voluntarios (
                    id UUID PRIMARY KEY,
                    updated_at TIMESTAMP NOT NULL DEFAULT now(),
                    activo BOOLEAN NOT NULL DEFAULT true
                )
                """
            ).format(sql.Identifier(schema))
        )
        connection.execute(
            sql.SQL("INSERT INTO {}.voluntarios (id) VALUES (%s)").format(
                sql.Identifier(schema)
            ),
            (voluntario_id,),
        )

    try:
        yield dsn, schema, voluntario_id
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )


def _count_active(dsn: str, schema: str) -> int:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            sql.SQL("SELECT count(*) FROM {}.voluntarios WHERE activo = true").format(
                sql.Identifier(schema)
            )
        ).fetchone()
    assert row is not None
    return int(row[0])


def test_concurrent_deactivate_one_winner(
    postgres_voluntario: tuple[str, str, str],
) -> None:
    """Dos transacciones concurrentes producen un ganador y un perdedor."""
    dsn, schema, voluntario_id = postgres_voluntario
    executor = _PostgresExecutor(dsn, schema, Barrier(2))

    assert _count_active(dsn, schema) == 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: voluntarios_service.deactivate_voluntario(
                    executor, voluntario_id
                ),
                range(2),
            )
        )

    assert Counter(results) == Counter({True: 1, False: 1})
    assert _count_active(dsn, schema) == 0


def test_postgres_dsn_required_hard_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ausencia del DSN falla de forma explícita; nunca hace skip."""
    monkeypatch.delenv(_POSTGRES_DSN_ENV, raising=False)

    with pytest.raises(pytest.fail.Exception, match=_POSTGRES_DSN_ENV):
        _require_postgres_dsn()
