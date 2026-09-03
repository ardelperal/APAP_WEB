"""FastAPI composition root for the local backend."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core.local_backend.db import LocalPostgresExecutor
from app.core.local_backend.rawsql import router as rawsql_router

healthz_router = APIRouter()
storage_router = APIRouter()
oauth_router = APIRouter()


def create_app(*, db_dsn: str = "", oauth_configured: bool = False) -> FastAPI:
    """Build the local FastAPI application and mount its routers."""
    if not db_dsn or not db_dsn.strip():
        raise RuntimeError("db_dsn is required for the local backend")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        executor = LocalPostgresExecutor(
            db_dsn,
            search_path=os.environ.get("APAP_LOCAL_DB_SCHEMA") or None,
        )
        application.state.local_postgres_executor = executor
        application.state.oauth_configured = oauth_configured
        try:
            yield
        finally:
            executor.close()

    application = FastAPI(title="APAP local backend", lifespan=lifespan)
    application.include_router(healthz_router)
    application.include_router(rawsql_router, prefix="/api")
    application.include_router(storage_router, prefix="/api")
    application.include_router(oauth_router, prefix="/api")
    return application


__all__ = ["create_app", "healthz_router", "oauth_router", "rawsql_router", "storage_router"]
