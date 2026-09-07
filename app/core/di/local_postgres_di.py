"""DI provider for the ``LocalPostgresExecutor`` (Coolify-hosted local backend).

Mirrors the shape of ``get_local_backend_client_dep`` so the rest of the
slice can migrate adapter-by-adapter without a single global cut-over.
Each call returns a fresh ``LocalPostgresExecutor`` wrapping the
DSN stored in ``APAP_LOCAL_DB_URL`` (``APAP_LOCAL_DB_SCHEMA`` optional,
defaults to ``public``).

Migration plan:

- Today (this commit): the helper exists; no caller has migrated.
- Subsequent commits: per-module migration replaces
  ``AuthUsersPort`` with ``LocalPostgresExecutor`` (sanidad,
  foster, entradas, etc.). Each migration is its own commit
  with its own verification.
- Final commit: ``app/main.py`` switches the lifespan from
  ``AuthUsersPort`` to ``LocalPostgresExecutor``; the legacy
  ``get_local_backend_client_dep`` is removed (or kept only for tests
  that pin the deprecation).
"""
from __future__ import annotations

from fastapi import Request

from app.core.data_access import SqlExecutor


def get_local_postgres_executor_dep(request: Request) -> SqlExecutor:
    """Return one ``LocalPostgresExecutor`` bound to the request lifetime.

    Reads the DSN + schema from the cached ``Settings`` singleton
    (``get_settings()`` is ``@functools.lru_cache(maxsize=1)``, so the
    lookup is O(1) after the first request). Constructs a fresh
    ``LocalPostgresExecutor`` per call; the executor is stateless
    (it opens a new psycopg connection per ``execute_sql``) so
    the cost is the cost of an object construction.

    The executor satisfies the ``SqlExecutor`` Protocol, so any
    code path that takes a ``SqlExecutor`` parameter (the
    application-layer use cases) accepts this without change.
    """
    settings = _get_settings()
    schema = settings.local_db_schema or None
    return _build_executor(settings.local_db_url, schema=schema)


def _get_settings():
    """Import-and-cache the cached settings singleton.

    Lazy-import keeps this module load-cheap (``get_settings`` reads
    ``.env`` at import time, which we want to defer until the first
    FastAPI request hits the helper).
    """
    from app.core.config import get_settings as _cached
    return _cached()


def _build_executor(dsn: str, *, schema: str | None) -> SqlExecutor:
    """Construct one ``LocalPostgresExecutor`` from the DSN + schema."""
    from app.core.local_backend.db import LocalPostgresExecutor

    return LocalPostgresExecutor(dsn, search_path=schema)


__all__ = ["get_local_postgres_executor_dep", "_build_executor"]
