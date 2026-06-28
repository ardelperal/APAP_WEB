"""SQL migration runner for the APAP_WEB web database (schema plane).

The web application's runtime cold-start calls
``app.core.migration.sql_runner.apply_sql_migrations`` in the lifespan
(see ``app/main.py:62``). Only the SQL runner + the migration files
under ``app/core/migration/sql/`` ship in the production wheel.

The ETL one-time (reconcile, diff_engine, shadow_state, derivation,
semantic_events, lock, cli, sync_state, legacy_reader, web_reader,
dysflow_client, reporting) and the YAML mappings live in the
top-level ``migration/`` package, which is NOT in the wheel. See
``migration/__init__.py`` for the public surface.
"""

from __future__ import annotations

from app.core.migration.sql_runner import apply_sql_migrations

__all__ = ["apply_sql_migrations"]
