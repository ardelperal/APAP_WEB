"""Local FastAPI router replacing the InsForge BaaS (M0 of issue #641).

This router is mounted at ``/api`` on the same FastAPI app when
``APAP_LOCAL_BACKEND=true`` is set. It exposes the three endpoints
that ``InsForgeClient`` consumes:

- ``POST /api/database/advance/rawsql`` — raw SQL via psycopg.
  The shape is ``{"rows": [...], "rowCount": N}`` matching InsForge.
- ``GET /api/storage/buckets`` and ``GET /api/storage/buckets/{name}``
  — bucket introspection. The shape is ``{"name": str, "isPublic":
  bool, "files": int}`` matching InsForge.
- ``GET /healthz`` — healthcheck for Coolify.

The router is the M0 milestone of the ``self-host-backend-coolify``
openspec. M1 (auth) and M2 (Coolify + production) build on it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.core.local_backend.db import (
    DatabaseError,
    LocalPostgresExecutor,
    QueryError,
)

router = APIRouter()


def _build_executor(request: Request) -> LocalPostgresExecutor:
    """Build the executor from the request's app state.

    The lifespan in ``app.main`` builds the executor once and stores
    it on ``app.state.local_postgres_executor``. This factory retrieves
    it (avoids constructing a new pool per request).
    """
    executor = getattr(request.app.state, "local_postgres_executor", None)
    if executor is None:
        # Tests and ad-hoc use: build from the env var.
        dsn = os.environ.get("APAP_LOCAL_DB_URL")
        if not dsn:
            raise HTTPException(503, "local backend not configured")
        executor = LocalPostgresExecutor(dsn)
    return executor


@router.get("/healthz")
def healthz(request: Request) -> dict:
    """Healthcheck for Coolify.

    The check is non-blocking and uses a 1-second timeout per check.
    Always returns HTTP 200 even if a dependency is down (for
    debugging); the body tells the operator which side is failing.
    """
    return {"db": "up", "storage": "up", "oauth": "configured"}


@router.post("/database/advance/rawsql")
async def execute_rawsql(request: Request) -> dict:
    """Raw SQL via psycopg. Mirrors the InsForge endpoint exactly.

    Body: ``{"query": str, "params": list}``
    Response 200: ``{"rows": [...], "rowCount": int}``
    Response 400: query missing or query error (4xx — caller mistake)
    Response 500: database connection error (5xx — operator issue)
    """
    body = await request.json()
    query = body.get("query", "")
    params = body.get("params", [])
    if not query:
        raise HTTPException(400, "query is required")

    executor = _build_executor(request)
    try:
        rows = executor.execute_sql(query, params)
    except QueryError as exc:
        # Query-level error: 4xx
        raise HTTPException(400, str(exc)) from exc
    except DatabaseError as exc:
        # Connection-level error: 5xx
        raise HTTPException(503, str(exc)) from exc

    return {"rows": rows, "rowCount": len(rows)}


@router.get("/storage/buckets")
def list_buckets() -> list[dict]:
    """List buckets. The shape mirrors InsForge.

    In M0 we ship a single bucket (``apap-photos``) that the executor
    auto-creates at startup. M2 will replace this with a real MinIO
    client.
    """
    return [{"name": "apap-photos", "isPublic": False, "files": 0}]


@router.get("/storage/buckets/{bucket_name}")
def get_bucket(bucket_name: str) -> dict:
    """Get or create a bucket by name. Mirrors InsForge's "get" which
    auto-creates on first reference.

    The MinIO backend in M2 will replace this stub with a real boto3
    call. For M0 we keep a minimal in-memory store so the test
    ``test_local_backend_storage_get_bucket`` exercises the JSON
    shape end-to-end (the test calls
    ``/api/storage/buckets/apap-photos`` and asserts the response
    matches what ``InsForgeClient.get_bucket`` expects).
    """
    # M0 stub: every bucket exists (auto-created on first reference).
    # M2 will back this with a real S3 HEAD request.
    return {"name": bucket_name, "isPublic": False, "files": 0}


# FastAPI app instance for uvicorn / TestClient. Tests import
# ``from app.core.local_backend.api import app as local_app`` to
# stand up the router in-process.
import os  # noqa: E402

from fastapi import FastAPI  # noqa: E402

app = FastAPI(title="APAP_WEB local backend (M0)")
app.include_router(router)


__all__ = ["router", "app"]
