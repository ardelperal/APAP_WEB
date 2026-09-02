"""FastAPI app for the local backend (M0 of self-host-backend-coolify, issue #641).

The local backend is a **separate FastAPI app** — not a router mounted
on ``app.main``. The user-approved architecture in the session prior
to this one keeps the lifespans independent: ``app.main`` provisions
the schema against InsForge (or against the local DB when
``APAP_LOCAL_BACKEND=true``); the local backend has its own lifespan
that constructs the ``LocalPostgresExecutor`` from
``APAP_LOCAL_DB_URL``.

The router mounts each handler at its documented path under ``/api``
(or root for ``/healthz``). The lifespan builds the executor once
at startup and stores it on ``app.state.local_postgres_executor``;
the handlers retrieve it from there. M2 (Coolify + production) wraps
this app in a separate Docker container behind coolify-proxy.

Hard rules (web-tdd-philosophy):
- Rule 1 (fixture gate): the lifespan runs in the test via
  ``httpx.AsyncClient(ASGITransport=app)``.
- Rule 4 (no humo): the lifespan raises on missing DSN, the executor
  wraps psycopg errors into typed exceptions, the handlers translate
  those to HTTP status codes.
- Rule 8 (no production mutation): the local backend runs in-process
  against the integration conftest's ephemeral Postgres.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.local_backend.db import LocalPostgresExecutor
from app.core.local_backend.healthz import router as healthz_router
from app.core.local_backend.oauth_google import router as oauth_router
from app.core.local_backend.rawsql import router as rawsql_router
from app.core.local_backend.storage import router as storage_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the LocalPostgresExecutor at startup; tear down at shutdown.

    Reads ``APAP_LOCAL_DB_URL`` (required) and ``APAP_LOCAL_DB_SCHEMA``
    (optional, default ``public``) from the environment. The
    integration tests pass the ephemeral schema name via
    ``APAP_LOCAL_DB_SCHEMA`` so the executor queries the right namespace.
    M0 hard-fails on missing DSN: the local backend is not optional.
    M2 (production) will surface a more useful error to the operator.
    """
    dsn = os.environ.get("APAP_LOCAL_DB_URL")
    if not dsn:
        raise RuntimeError(
            "APAP_LOCAL_DB_URL is not set. The local backend requires "
            "a Postgres DSN at startup. Set it in the environment or "
            ".env (see docs/runbooks/self-host-backend.md)."
        )
    search_path = os.environ.get("APAP_LOCAL_DB_SCHEMA")
    app.state.local_postgres_executor = LocalPostgresExecutor(
        dsn, search_path=search_path
    )
    try:
        yield
    finally:
        # The current implementation builds a fresh connection per
        # execute() call (no pool in M0). The hook is here for M2 when
        # a real connection pool arrives.
        pass


def create_app() -> FastAPI:
    """App factory for the local backend.

    A factory (not a module-level instance) keeps the tests hermetic
    and lets the lifespan be properly initialised by the test
    client (ASGITransport). Module-level instances skip the lifespan
    in some test setups; factories do not.
    """
    app = FastAPI(
        title="APAP_WEB local backend (M0)",
        lifespan=lifespan,
    )
    app.include_router(rawsql_router, prefix="/api")
    app.include_router(storage_router, prefix="/api")
    app.include_router(healthz_router)
    app.include_router(oauth_router, prefix="/api")
    return app


__all__ = ["create_app", "lifespan"]
