"""Health probe endpoint for the local backend (M0)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request

from app.core.local_backend.db import DatabaseError, QueryError

healthz_router = APIRouter()

_GOOGLE_CLIENT_ID_ENV = "APAP_GOOGLE_CLIENT_ID"


def _probe_db(request: Request) -> str:
    """Run a ``SELECT 1`` probe against the lifespan-managed executor.

    The probe MUST NOT raise; any exception (connection refused, query
    error, executor missing) surfaces as ``db: down``. This matches the
    R1 acceptance contract.
    """
    executor = getattr(request.app.state, "local_postgres_executor", None)
    if executor is None:
        return "down"
    try:
        executor.execute("SELECT 1")
    except (DatabaseError, QueryError):
        return "down"
    except Exception:
        return "down"
    return "up"


@healthz_router.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    """Return the M0 health envelope: ``db``, ``storage``, ``oauth``."""
    return {
        "db": _probe_db(request),
        "storage": "up",
        "oauth": "configured" if os.environ.get(_GOOGLE_CLIENT_ID_ENV) else "missing",
    }


__all__ = ["healthz_router", "healthz"]
