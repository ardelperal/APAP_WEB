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

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, NoReturn

import psycopg

from app.core.data_access import NestedTransactionError, SqlExecutor


class DatabaseError(RuntimeError):
    """Connection-level failure (DSN bad, network down, pool exhausted).

    Mapped to HTTP 5xx by the FastAPI layer.
    """


class QueryError(RuntimeError):
    """The query reached Postgres but the server rejected it (syntax, FK, etc).

    Mapped to HTTP 4xx by the FastAPI layer.
    """


_DOLLAR_PLACEHOLDER = re.compile(r"\$(\d+)")


def _to_client_placeholders(query: str, params: tuple | list | None) -> tuple[str, list[Any]]:
    """Translate ``$N`` placeholders and params for psycopg3's ClientCursor.

    The query builders use Postgres ``$N`` placeholders, which may repeat
    (``$1`` twice) or appear out of order (``SET x = $2 WHERE id = $1``).
    psycopg3's client-side cursor only understands positional ``%s``, so
    each ``$N`` occurrence becomes one ``%s`` and the params are rebuilt in
    occurrence order (``params[N-1]`` per occurrence). Literal ``%`` is
    escaped as ``%%`` so client-side formatting leaves it alone. A ``$N``
    with no matching param raises :class:`QueryError` instead of binding
    ``None`` or a neighbour's value (issue #944).
    """
    values = list(params or [])
    order: list[int] = []

    def _record(match: re.Match[str]) -> str:
        order.append(int(match.group(1)))
        return "%s"

    rewritten = _DOLLAR_PLACEHOLDER.sub(_record, query.replace("%", "%%"))
    if not order:
        return query, values
    return rewritten, _bind_in_occurrence_order(order, values)


def _bind_in_occurrence_order(order: list[int], values: list[Any]) -> list[Any]:
    """Return one value per ``$N`` occurrence, failing on an unbound ``$N``."""
    missing = [n for n in order if not 1 <= n <= len(values)]
    if missing:
        raise QueryError(
            f"placeholder ${missing[0]} has no bound parameter ({len(values)} given)"
        )
    return [values[n - 1] for n in order]


def _translate_psycopg_error(exc: psycopg.Error) -> QueryError | DatabaseError:
    """Map a psycopg error to the Protocol-level exception callers expect.

    A Postgres-rejected query (syntax, FK, unique violation) carries a
    SQLSTATE and becomes a ``QueryError``; anything without one
    (connection-level) becomes a ``DatabaseError``. psycopg3 exposes the
    code as ``sqlstate`` (``pgcode`` was the psycopg2 name).
    """
    if getattr(exc, "sqlstate", None) is not None:
        return QueryError(str(exc))
    return DatabaseError(str(exc))


def _fetch_rows(cur: Any) -> list[Any]:
    """Return every row from an already-executed cursor, or ``[]``.

    ``INSERT``/``UPDATE``/``DELETE`` statements have nothing to fetch;
    psycopg raises :class:`psycopg.ProgrammingError` in that case, which
    this helper turns into an empty result instead of propagating it.
    """
    try:
        return list(cur.fetchall())
    except psycopg.ProgrammingError:
        return []


def _rows_as_dicts(rows: list[Any], description: Any) -> list[dict[str, Any]]:
    """Convert plain tuple rows to ``list[dict]`` using the cursor description.

    A no-op when ``rows`` is empty or already made of dicts (psycopg's
    ``dict_row`` row factory, if ever configured, would produce those).
    """
    if not rows or isinstance(rows[0], dict):
        return rows
    columns = [col[0] for col in description]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _run_on_cursor(cur: Any, query: str, params: tuple | list | None) -> list[dict[str, Any]]:
    """Execute ``query`` on an already-open cursor and return rows as dicts.

    Shared by :meth:`LocalPostgresExecutor.execute_sql` (its own
    connection, commits per call) and the bound executor
    :meth:`LocalPostgresExecutor.transaction` yields (a shared connection,
    the caller controls commit/rollback) so both apply the identical
    ``$N``-rewrite, row-dict conversion and error translation. Always
    raises :class:`QueryError`/:class:`DatabaseError`, never a raw
    ``psycopg.Error``.
    """
    query, values = _to_client_placeholders(query, params)
    try:
        cur.execute(query, values)
        rows = _fetch_rows(cur)
    except psycopg.Error as exc:
        raise _translate_psycopg_error(exc) from exc
    return _rows_as_dicts(rows, cur.description)


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

    def __init__(self, dsn: str, search_path: str | None = None) -> None:
        self._dsn = dsn
        self._search_path = search_path

    def close(self) -> None:
        """No-op: each call to ``execute_sql`` opens/closes its own connection."""

    def _connect(self):
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

    def execute_sql(self, query: str, params: tuple | list | None = None) -> list[dict[str, Any]]:
        # ``$N`` -> ``%s`` translation (with param reordering) is shared
        # via ``_run_on_cursor``/``_to_client_placeholders`` (issue #944).
        with self._connect() as conn:
            cur = conn.cursor()
            try:
                rows = _run_on_cursor(cur, query, params)
                conn.commit()
            except (QueryError, DatabaseError):
                conn.rollback()
                raise
            except psycopg.Error as exc:
                # COMMIT itself failed (e.g. deferred constraint).
                conn.rollback()
                raise _translate_psycopg_error(exc) from exc
            finally:
                cur.close()
        return rows

    @contextmanager
    def transaction(self) -> Iterator[SqlExecutor]:
        """Open one connection and run several statements as one atomic unit.

        Use this when a business flow needs more than one ``execute_sql``
        call (e.g. a Python loop, or a read that must observe an earlier
        write in the same unit of work) to commit or roll back together —
        see A-02..A-04 (#914-#916): the adopciones/acogidas/lifecycle/
        chip-cascade flows. When the atomic unit is expressible as ONE SQL
        statement, prefer a CTE instead — it needs no held-open connection
        across the call boundary; see
        ``app/modules/entradas/batch_service.py::commit_batch`` for the
        pattern (batch-staging rows copied into ``entradas`` atomically).

        Yields a bound executor satisfying :class:`SqlExecutor` (so
        existing helpers such as ``record_event(client, ...)`` work
        unchanged inside the block). COMMIT on clean exit; ROLLBACK and
        re-raise on any exception; the connection is always closed.
        Calling ``transaction()`` again on the yielded executor raises
        :class:`NestedTransactionError` — no savepoints.
        """
        conn = self._connect()
        bound = _BoundTransactionExecutor(conn)
        try:
            yield bound
        except Exception:
            conn.rollback()
            raise
        else:
            try:
                conn.commit()
            except psycopg.Error as exc:
                # COMMIT itself failed (e.g. deferred constraint).
                raise _translate_psycopg_error(exc) from exc
        finally:
            conn.close()


class _BoundTransactionExecutor:
    """``SqlExecutor`` bound to a single connection held open by ``transaction()``.

    ``execute_sql`` runs on the shared connection WITHOUT committing per
    statement (the enclosing :meth:`LocalPostgresExecutor.transaction`
    commits or rolls back once, on exit). Nesting a transaction on this
    bound executor is rejected — there are no savepoints.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def execute_sql(self, query: str, params: tuple | list | None = None) -> list[dict[str, Any]]:
        cur = self._conn.cursor()
        try:
            return _run_on_cursor(cur, query, params)
        finally:
            cur.close()

    def transaction(self) -> NoReturn:
        raise NestedTransactionError(
            "nested transaction() is not supported: this executor is already "
            "bound to a connection opened by LocalPostgresExecutor.transaction()"
        )


__all__ = ["LocalPostgresExecutor", "DatabaseError", "QueryError"]
