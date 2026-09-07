"""``POST /api/database/advance/rawsql`` handler (M0 of self-host-backend-coolify).

The LocalBackend REST API exposes a privileged ``/api/database/advance/rawsql``
endpoint that ``AuthUsersPort.execute_sql`` consumes. The local backend
re-implements that endpoint against a Postgres connection, reusing the
``LocalPostgresExecutor`` from ``app.core.local_backend.db`` so the
contract (``{"rows": [...], "rowCount": N}``) is identical to LocalBackend's.

**Auth gate (issue #680):** every request must carry
``Authorization: Bearer <APAP_RAWSQL_AUTH_TOKEN>`` matching
:attr:`Settings.rawsql_auth_token`. The comparison is constant-time
(``hmac.compare_digest``) to defeat timing probes; an empty / missing /
mismatched header returns 401 without touching the executor. The
``Settings`` startup validator (issue #275 / §32.P2) refuses to boot
when ``APAP_RAWSQL_AUTH_TOKEN`` is empty or shorter than the shared-
secret floor, so the handler never sees a request unless the operator
explicitly opted in.

The handler still uses ``app.state.local_postgres_executor`` for the
DB call (no new I/O is added by this change — the executor already
exists on the lifespan-managed app state). The default-deny model
means the endpoint is functionally a no-op unless the env var is
set, which matches the InsForge upstream's ``Authorization: Bearer
{service_key}`` requirement.

Error mapping:
- ``QueryError`` (query rejected by Postgres: syntax, FK, constraint) → 400.
- ``DatabaseError`` (connection-level failure: bad DSN, network down)
  → 503 (service unavailable, mirrors Postgres-down semantics).
- 401 Unauthorized for missing / invalid ``Authorization`` header
  (handled by ``_require_rawsql_token`` before the executor call).
"""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.local_backend.db import DatabaseError, LocalPostgresExecutor, QueryError

router = APIRouter()


def _require_rawsql_token(authorization: str | None) -> None:
    """Validate the ``Authorization: Bearer <token>`` header against settings.

    Default-deny: any mismatch (missing, wrong scheme, wrong token,
    empty configured secret) raises 401 BEFORE any DB call. The
    comparison uses :func:`hmac.compare_digest` so a timing-attack
    probe cannot infer the token length or content. The configured
    secret is read via :func:`app.core.config.get_settings` so the
    cache is shared with the rest of the app.
    """
    settings = get_settings()
    expected = settings.rawsql_auth_token
    if not expected:
        # Operator never set the env var (startup would have failed
        # in production; debug mode is the only path that reaches here
        # with an empty secret — we still deny in that case).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="rawsql endpoint disabled (server has no APAP_RAWSQL_AUTH_TOKEN configured)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = authorization.removeprefix("Bearer ").strip()
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid rawsql bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/database/advance/rawsql")
async def execute_rawsql(
    request: Request,
    payload: dict[str, Any],
    authorization: Annotated[
        str | None,
        Header(
            description=(
                "Required: ``Bearer <APAP_RAWSQL_AUTH_TOKEN>``. The handler "
                "is the compatibility surface that mirrors LocalBackend's "
                "``/api/database/advance/rawsql`` upstream; both layers "
                "demand a shared secret so a misconfigured mount cannot "
                "execute arbitrary SQL (issue #680)."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """Execute a raw SQL statement and return the rows.

    Body shape (matches what the production ``AuthUsersPort`` sends):
        ``{"query": str, "params": list | None}``

    Response shape (matches LocalBackend's envelope):
        ``{"rows": [{"col": val, ...}, ...], "rowCount": N}``

    Raises (translated to HTTP status by ``app.exception_handler`` or the
    FastAPI default handlers):
        - 401 Unauthorized if the ``Authorization`` header is missing,
          malformed, or its bearer token does not match
          ``APAP_RAWSQL_AUTH_TOKEN`` (default-deny; issue #680).
        - ``QueryError`` → 400 Bad Request (caller's query is malformed).
        - ``DatabaseError`` → 503 Service Unavailable (Postgres down).
    """
    _require_rawsql_token(authorization)

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
