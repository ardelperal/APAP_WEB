"""Postgres executor for the local backend (M0 of self-host-backend-coolify, issue #641).

The local FastAPI router (``app.core.local_backend.api``) uses this
executor to run SQL against the same Postgres instance that the
integration tests use. The shape of the return value matches what
``InsForgeClient.execute_sql`` consumes (``{"rows": [...], "rowCount": N}``).

Why a separate module:
- The local backend runs as a separate app from ``app.main`` (the
  user-approved architecture in the session prior to this one). The
  executor is a private detail of the local backend module.
- The integration tests pin the executor's contract via
  ``self_host_schema`` (the conftest's ephemeral schema). The test
  asserts that ``search_path`` is applied at every connect, not just
  at the first one.

Hard rules (web-tdd-philosophy):
- Rule 4 (no humo): tests assert return shapes, placeholder style,
  error classification — never absence-of-error.
- Rule 8 (no production mutation): tests run against the
  self_host_schema ephemeral Postgres; no real InsForge touched.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg


class DatabaseError(RuntimeError):
    """Connection-level failure (DSN bad, network down, pool exhausted).

    Mapped to HTTP 5xx by the FastAPI layer.
    """


class QueryError(RuntimeError):
    """The query reached Postgres but the server rejected it (syntax, FK, etc).

    Mapped to HTTP 4xx by the FastAPI layer.
    """


_DOLLAR_TO_PERCENT = re.compile(r"\$(\d+)")


class LocalPostgresExecutor:
    """psycopg wrapper that satisfies the ``SqlExecutor`` Protocol.

    The integration conftest (``tests/integration/conftest.py``) provides
    ``self_host_schema`` which has a working ``execute_sql``. This
    executor builds its own psycopg connection per request (no pool in
    M0).

    The optional ``search_path`` is set after each connect. The
    integration tests use this to point the executor at the ephemeral
    schema (which lives outside the default ``public`` search_path).
    """

    def __init__(self, dsn: str, search_path: str | None = None) -> None:
        self._dsn = dsn
        self._search_path = search_path

    def _connect(self) -> psycopg.Connection:
        """Open a new connection. Real connections in production; test
        connections in tests via the same DSN (the integration
        conftest provisions the schema on the same Postgres instance).
        """
        conn = psycopg.connect(self._dsn)
        if self._search_path:
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{self._search_path}"')
            conn.commit()
        return conn

    def execute(
        self, query: str, params: list | tuple | None = None
    ) -> list[dict[str, Any]]:
        """Run the query and return ``[{"col": val, ...}, ...]``.

        INSERT/UPDATE/DELETE return ``[]`` (no rows to fetch) — that is
        the contract the rest of the application already assumes.
        Postgres native ``$N`` placeholders are rewritten to ``%s``
        for psycopg3 ClientCursor (the integration conftest does the
        same rewriting in its ``_expand_params_for_placeholder_style``).
        """
        # Rewrite ``$N`` to ``%s`` because psycopg3 ClientCursor counts
        # ``%s`` placeholders, not ``$N``. The wire protocol sees the
        # original ``$N`` (psycopg3 re-numbers).
        if "$" in query:
            query = _DOLLAR_TO_PERCENT.sub(r"%s", query)
        try:
            with self._connect() as conn:
                cur = conn.cursor()
                try:
                    cur.execute(query, params or [])
                except psycopg.Error as exc:
                    conn.rollback()
                    # Classify the failure: query-level errors (syntax, FK,
                    # constraint violation) are 4xx — caller mistakes.
                    # Connection errors (operational) bubble up as
                    # ``DatabaseError`` so the FastAPI layer can map to 5xx.
                    if getattr(exc, "sqlstate", None) is not None:
                        raise QueryError(str(exc)) from exc
                    raise DatabaseError(str(exc)) from exc
                try:
                    rows: list[Any] = list(cur.fetchall())
                except psycopg.ProgrammingError:
                    # INSERT/UPDATE/DELETE: no rows to fetch
                    rows = []
                conn.commit()
                if rows and not isinstance(rows[0], dict):
                    # Map tuples to dicts by cursor description (matches
                    # ``dict_row`` behaviour when the production path uses
                    # it). Tests using the conftest's cursor get dicts
                    # directly; this branch is for the executor's own
                    # connections which use the default tuple factory.
                    # ``cur.description`` is ``None`` only for statements
                    # that did not produce a result set; the branch above
                    # already handles that (``rows == []``), so the type
                    # narrowing is safe.
                    # Map tuples to dicts by cursor description. This branch
                    # only runs when ``rows`` is non-empty (the outer ``if``
                    # guards it) and ``rows[0]`` is not a dict (the default
                    # psycopg cursor returns tuples). The branch therefore
                    # always iterates over the tuple rows; the cast below is
                    # a documentation marker for mypy because psycopg's
                    # ``cur.fetchall`` returns ``list[tuple[Any, ...]]`` but
                    # the consumer (the caller of ``execute``) expects
                    # ``list[dict[str, Any]]``.
                    # mypy narrow: ``cur.description`` is non-None because the
                    # outer ``if`` guarantees ``rows`` is non-empty (which only
                    # happens for statements that produced a result set).
                    description_list = cur.description
                    assert description_list is not None
                    columns = [col[0] for col in description_list]
                    # The producer side is psycopg's default tuple factory;
                    # the consumer side (``InsForgeClient.execute_sql``)
                    # expects ``list[dict[str, Any]]``. We map tuples to dicts
                    # here so the contract is uniform.
                    rows = [
                        dict(zip(columns, row, strict=True)) for row in rows
                    ]
                return rows
        except psycopg.Error as exc:
            # Connection-level failure during ``_connect`` (DSN bad, network
            # down, pool exhausted). Always DatabaseError — no ``sqlstate``
            # attribute on OperationalError for connection failures, so
            # fall through to the default.
            raise DatabaseError(str(exc)) from exc


__all__ = ["LocalPostgresExecutor", "DatabaseError", "QueryError"]
