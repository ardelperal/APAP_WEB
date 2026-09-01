"""Postgres executor for the local backend (M0 of self-host-backend-coolify, issue #641).

The local FastAPI router (``app.core.local_backend.api``) uses this
executor to run SQL against the same Postgres instance that the
integration tests use. The shape of the return value matches what
``InsForgeClient.execute_sql`` expects (``list[dict]``) so the rest of
the application does not need to know whether the backend is local
Postgres or the InsForge BaaS.

Why a separate module: the FastAPI layer is a thin HTTP wrapper. The
SQL execution is a non-trivial piece of logic (connection pooling,
error mapping, placeholder rewriting) that the unit tests pin
without spinning up uvicorn. The api.py module imports this and
translates ``DatabaseError`` to HTTP 5xx, ``QueryError`` to HTTP 4xx.
"""

from __future__ import annotations

from typing import Any, Protocol

import psycopg


class DatabaseError(RuntimeError):
    """Connection-level failure (DSN bad, network down, pool exhausted).

    Mapped to HTTP 5xx by the FastAPI layer.
    """


class QueryError(RuntimeError):
    """The query reached Postgres but the server rejected it (syntax, FK, etc).

    Mapped to HTTP 4xx by the FastAPI layer.
    """


class LocalPostgresExecutor:
    """psycopg2 wrapper that satisfies the ``SqlExecutor`` Protocol.

    The integration conftest (``tests/integration/conftest.py``) provides
    ``self_host_schema`` which has a working ``execute_sql``. This
    executor builds its own psycopg connection from the DSN, so the same
    code path is exercised in production and in tests.

    INSERT/UPDATE/DELETE return ``[]`` (no rows to fetch) — that is
    the contract the rest of the application already assumes. Postgres
    native ``$N`` placeholders are used; no rewriting is performed
    (Postgres supports them natively).
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        """Open a new connection. Real connections in production; test
        connections in tests via the same DSN (the integration
        conftest provisions the schema on the same Postgres instance).
        """
        return psycopg.connect(self._dsn)

    def execute(
        self, query: str, params: tuple | list | None = None
    ) -> list[dict[str, Any]]:
        # psycopg3 ClientCursor counts ``%s`` placeholders, not ``$N``.
        # Rewrite the query to ``%s`` before execution. The wire
        # protocol sees the original ``$N`` (psycopg3 re-numbers).
        # See tests/integration/conftest.py ``_to_client_placeholder_style``
        # for the rationale.
        if "$" in query:
            import re
            query = re.sub(r"\$(\d+)", r"%s", query)
        with self._connect() as conn:
            cur = conn.cursor()
            try:
                cur.execute(query, params or [])
                try:
                    rows = list(cur.fetchall())
                except psycopg.ProgrammingError:
                    # INSERT/UPDATE/DELETE: no rows to fetch
                    rows = []
                conn.commit()
                if rows and not isinstance(rows[0], dict):
                    columns = [col[0] for col in cur.description]
                    rows = [dict(zip(columns, row)) for row in rows]
                return rows
            except psycopg.Error as exc:
                conn.rollback()
                if getattr(exc, "pgcode", None) is not None:
                    raise QueryError(str(exc)) from exc
                raise DatabaseError(str(exc)) from exc
            finally:
                cur.close()


__all__ = ["LocalPostgresExecutor", "DatabaseError", "QueryError"]
