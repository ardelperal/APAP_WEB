"""``POST /api/database/advance/rawsql`` handler (M0 of self-host-backend-coolify).

The LocalBackend REST API exposes a privileged ``/api/database/advance/rawsql``
endpoint that ``AuthUsersPort.execute_sql`` consumes. The local backend
re-implements that endpoint against a Postgres connection, reusing the
``LocalPostgresExecutor`` from ``app.core.local_backend.db`` so the
contract (``{"rows": [...], "rowCount": N}``) is identical to LocalBackend's.

Error mapping:
- ``QueryError`` (query rejected by Postgres: syntax, FK, constraint) → 400.
- ``DatabaseError`` (connection-level failure: bad DSN, network down)
  → 503 (service unavailable, mirrors Postgres-down semantics).

Hard rules (web-tdd-philosophy):
- Rule 4 (no humo): the handler translates the executor's typed
  exceptions into HTTP status codes; tests assert the status, not the
  absence of an exception.
- Rule 8 (no production mutation): the executor reads from the
  integration conftest's ephemeral schema via the lifespan-set
  ``APAP_LOCAL_DB_SCHEMA``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.local_backend.db import DatabaseError, LocalPostgresExecutor, QueryError

router = APIRouter()


@router.post("/database/advance/rawsql")
async def execute_rawsql(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute a raw SQL statement and return the rows.

    Body shape (matches what the production ``AuthUsersPort`` sends):
        ``{"query": str, "params": list | None}``

    Response shape (matches LocalBackend's envelope):
        ``{"rows": [{"col": val, ...}, ...], "rowCount": N}``

    Raises (translated to HTTP status by ``app.exception_handler`` or the
    FastAPI default handlers):
        - ``QueryError`` → 400 Bad Request (caller's query is malformed).
        - ``DatabaseError`` → 503 Service Unavailable (Postgres down).
    """
    query = payload.get("query")
    if not isinstance(query, str) or not query:
        # Caller-side mistake: missing or non-string ``query``.
        # Translate to ``QueryError`` so the 400 mapping is uniform.
        raise QueryError("payload must include a non-empty 'query' string")

    params = payload.get("params")
    if params is not None and not isinstance(params, (list, tuple)):
        raise QueryError("payload 'params' must be a list or tuple if present")

    executor: LocalPostgresExecutor = request.app.state.local_postgres_executor
    rows = executor.execute(query, params)
    return {"rows": rows, "rowCount": len(rows)}


__all__ = ["router", "execute_rawsql", "DatabaseError", "QueryError"]
