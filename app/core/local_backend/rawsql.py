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
mismatched header returns the same generic 401 without touching the
executor. The separate LocalBackend lifespan refuses to boot when
``APAP_RAWSQL_AUTH_TOKEN`` is empty or shorter than 32 characters;
``app.main`` does not require the token because it never mounts this router.

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

from app.core.local_backend.db import DatabaseError, LocalPostgresExecutor, QueryError

router = APIRouter()


def _require_rawsql_token(authorization: str | None, expected: str) -> None:
    """Validate the bearer credential without exposing failure details.

    Default-deny: any mismatch (missing, wrong scheme, wrong token,
    empty configured secret) raises the same 401 BEFORE any DB call. The
    comparison uses :func:`hmac.compare_digest` so a timing-attack
    probe cannot infer the token length or content. The configured
    expected secret comes from lifespan-managed app state, keeping this
    privileged router independent from the main web application's startup.
    """
    bearer_prefix = "Bearer "
    has_bearer_scheme = False
    presented = ""
    if authorization is not None and authorization.startswith(bearer_prefix):
        has_bearer_scheme = True
        presented = authorization[len(bearer_prefix) :]
    credentials_match = hmac.compare_digest(presented, expected)
    if not expected or not presented or not has_bearer_scheme or not credentials_match:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
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
    expected_token = getattr(request.app.state, "rawsql_auth_token", "")
    _require_rawsql_token(authorization, expected_token)

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
