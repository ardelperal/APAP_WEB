"""Raw SQL endpoint for the local PostgreSQL backend."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.local_backend.db import (
    DatabaseError,
    QueryError,
    QueryResult,
    _safe_table,
)

router = APIRouter()
_SQL_KEYWORDS = frozenset("""
all alter and any array as asc avg between bigint boolean by case cast char
coalesce count create cross current_date date decimal default delete desc
distinct double drop else end exists extract false float foreign from full
group having ilike in inner insert int integer interval into is join json jsonb
key left like limit max min not nothing null numeric offset on or order outer
primary real recursive replace returning right select serial set smallint sum
table text then time timestamp timestamptz true truncate union update using uuid
values varchar when where with
""".split())
_STRING = re.compile(
    r"'(?:''|[^'])*'|\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$.*?\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$",
    re.DOTALL,
)
_SAFE_TOKEN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b")


def _outside_strings(query: str) -> str:
    """Remove string literals so SQL terminators remain visible."""
    return _STRING.sub("", query)


def _validate_query(query: str) -> None:
    """Reject unsafe identifiers, comments, and multiple statements."""
    outside = _outside_strings(query)
    if '"' in outside or "`" in outside or "--" in outside or "/*" in outside:
        raise QueryError("unsafe SQL identifier or SQL comment", "unsafe_sql_identifier")
    if ";" in outside:
        raise QueryError("only one SQL statement is allowed", "multiple_statements")
    for match in _SAFE_TOKEN.finditer(outside):
        if match.group(0).upper() not in _SQL_KEYWORDS:
            _safe_table(match.group(0))


def _error(status: int, code: str, detail: str) -> JSONResponse:
    """Build the stable JSON error envelope."""
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


@router.post("/database/advance/rawsql", response_model=None)
async def execute_rawsql(request: Request) -> dict[str, Any] | JSONResponse:
    """Execute one validated statement against the local Postgres DSN."""
    try:
        payload = await request.json()
    except Exception:
        return _error(400, "invalid_request", "request body must be valid JSON")
    if not isinstance(payload, dict):
        return _error(400, "invalid_request", "request body must be an object")
    if "query" not in payload or "params" not in payload:
        return _error(400, "invalid_request", "query and params are required")
    query = payload["query"]
    params = payload["params"]
    if not isinstance(query, str) or not query.strip():
        return _error(400, "invalid_request", "query must be a non-empty string")
    if params is not None and not isinstance(params, list):
        return _error(400, "invalid_request", "params must be a list or null")
    try:
        _validate_query(query)
    except QueryError as exc:
        return _error(400, exc.code, str(exc))
    executor = getattr(request.app.state, "local_postgres_executor", None)
    if executor is None:
        return _error(503, "database_error", "local backend is not initialized")
    try:
        result = executor.execute(query, params)
    except QueryError as exc:
        return _error(400, exc.code, str(exc))
    except DatabaseError:
        return _error(503, "database_error", "database is unavailable")
    rows = list(result) if result is not None else []
    rowcount = result.rowcount if isinstance(result, QueryResult) else len(rows)
    return {"rows": rows, "rowCount": rowcount}


__all__ = ["router", "execute_rawsql"]
