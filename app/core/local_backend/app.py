"""FastAPI app for the local backend (M0 of self-host-backend-coolify, issue #641).

The local backend is a **separate FastAPI app** — not a router mounted
on ``app.main``. The user-approved architecture in the session prior
to this one keeps the lifespans independent: ``app.main`` provisions
the schema against LocalBackend (or against the local DB when
``APAP_LOCAL_BACKEND=true``); the local backend has its own lifespan
that constructs the ``LocalPostgresExecutor`` from
``APAP_LOCAL_DB_URL``.

The router mounts each handler at its documented path under ``/api``
(or root for ``/healthz``). The lifespan builds the executor once
at startup and stores it on ``app.state.local_postgres_executor``;
the handlers retrieve it from there. M2 (Coolify + production) wraps
this app in a separate Docker container behind coolify-proxy.

M3.4 (issue #651) extends the lifespan to also wire the magic-link
port + SMTP transport + session secret onto ``app.state`` so the
magic-link router can read them.

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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.adapters.auth_local.magic_link_port import MagicLinkPortImpl
from app.core.config import Settings, StartupConfigError, get_settings
from app.core.local_backend.db import (
    DatabaseError,
    LocalPostgresExecutor,
    QueryError,
)
from app.core.local_backend.healthz import router as healthz_router
from app.core.local_backend.magic_link import router as magic_link_router
from app.core.local_backend.oauth_google import router as oauth_router
from app.core.local_backend.rawsql import router as rawsql_router
from app.core.local_backend.storage import router as storage_router
from app.core.mail.smtp_transport import SMTPMailTransport

_MIN_RAWSQL_AUTH_TOKEN_LENGTH = 32


def _validate_rawsql_auth_token(settings: Settings) -> str:
    """Return a strong raw-SQL token or fail the LocalBackend startup.

    This validation belongs to the separate LocalBackend process because
    only that app mounts the privileged raw-SQL compatibility endpoint.
    The main web application must not require an otherwise unused secret.
    """
    token = settings.rawsql_auth_token
    if not token:
        raise StartupConfigError("APAP_RAWSQL_AUTH_TOKEN", "empty")
    if len(token) < _MIN_RAWSQL_AUTH_TOKEN_LENGTH:
        raise StartupConfigError("APAP_RAWSQL_AUTH_TOKEN", "too_short")
    return token


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the LocalPostgresExecutor at startup; tear down at shutdown.

    Reads ``APAP_LOCAL_DB_URL`` (required) and ``APAP_LOCAL_DB_SCHEMA``
    (optional, default ``public``) from the environment. The
    integration tests pass the ephemeral schema name via
    ``APAP_LOCAL_DB_SCHEMA`` so the executor queries the right namespace.
    M0 hard-fails on missing DSN: the local backend is not optional.
    M2 (production) will surface a more useful error to the operator.

    M3.4 also wires:

    - ``MagicLinkPortImpl`` over the executor (so the magic-link
      router can persist tokens).
    - ``SMTPMailTransport`` over the cached settings (no-op when
      ``APAP_SMTP_HOST`` is unset).
    - ``session_secret`` (the lifespan reads it from
      ``APAP_SESSION_SECRET`` so the magic-link verify handler can
      sign the cookie).
    - ``rawsql_auth_token`` after enforcing the LocalBackend-only
      minimum length, so the raw-SQL router fails closed.
    """
    dsn = os.environ.get("APAP_LOCAL_DB_URL")
    if not dsn:
        raise RuntimeError(
            "APAP_LOCAL_DB_URL is not set. The local backend requires "
            "a Postgres DSN at startup. Set it in the environment or "
            ".env (see docs/runbooks/self-host-backend.md)."
        )
    settings = get_settings()
    rawsql_auth_token = _validate_rawsql_auth_token(settings)
    search_path = os.environ.get("APAP_LOCAL_DB_SCHEMA")
    executor = LocalPostgresExecutor(dsn, search_path=search_path)
    app.state.local_postgres_executor = executor

    # M3.4 wiring: magic-link port + SMTP transport + session secret.
    app.state.rawsql_auth_token = rawsql_auth_token
    app.state.magic_link_port = MagicLinkPortImpl(executor)
    app.state.smtp_transport = SMTPMailTransport(settings)
    app.state.session_secret = settings.session_secret
    # Public base URL the verify link points at. Defaults to the
    # ``APAP_PUBLIC_BASE_URL`` env var or ``http://127.0.0.1:8000``;
    # production sets it to ``https://apap.romancaba.com`` via the
    # Coolify env-var injection in M2.
    app.state.public_base_url = os.environ.get("APAP_PUBLIC_BASE_URL", "http://127.0.0.1:8000")

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

    @app.exception_handler(QueryError)
    async def _on_query_error(request: Request, exc: QueryError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "query_error", "detail": str(exc)},
        )

    @app.exception_handler(DatabaseError)
    async def _on_database_error(request: Request, exc: DatabaseError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": "database_error", "detail": str(exc)},
        )

    app.include_router(rawsql_router, prefix="/api")
    app.include_router(storage_router, prefix="/api")
    app.include_router(healthz_router)
    app.include_router(oauth_router, prefix="/api")
    app.include_router(magic_link_router, prefix="/api")
    return app


__all__ = ["create_app", "lifespan"]
