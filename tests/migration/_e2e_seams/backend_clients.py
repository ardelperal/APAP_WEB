"""Test seam: real-backend clients that satisfy the migration _InsForgeLike protocol.

This module lets the E2E migration tests run ``apply_legacy_to_web`` and
``apply_web_to_legacy`` against a real database (Postgres ephemeral or
InsForge) rather than the FakeInsForge in-memory shim used by the rest
of the migration test suite.

The seam wraps existing clients:

  * ``PostgresBackendClient`` wraps the ``ephemeral_postgres`` fixture's
    underlying psycopg connection. The schema is provisioned with the
    APAP_WEB domain tables (animales, voluntarios, entradas, etc.) plus
    the catalogos (catalogos_motivos, catalogos_origenes, etc.) and
    the web-only feature shadow state table. Migrations need the
    catalogos to resolve the contrato type FK, so we seed them.

  * ``InsForgeBackendClient`` is a thin wrapper over the production
    ``app.core.insforge.LocalPostgresExecutor`` (which already exposes the
    same ``execute_sql`` signature). It is used in CI when an
    InsForge project is provisioned; locally, when no InsForge env
    vars are set, the E2E atom uses the Postgres backend.

The two clients are NOT mutually exclusive — the test atom picks one
based on the ``APAP_INSFORGE_URL`` env var. The InsForge client is
preferred when available because it is the production target.
"""

from __future__ import annotations

import os
from typing import Any, Protocol


class InsForgeLike(Protocol):
    """Structural type satisfied by both backend clients.

    Mirrors the migration ``_InsForgeLike`` protocol in
    ``migration/apply.py``. We re-declare it here so the test seam
    does not need to import from the migration package (which would
    require sys.path manipulation from the test runner).
    """

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class PostgresBackendClient:
    """Adapter that exposes the integration conftest's ephemeral Postgres
    as an ``_InsForgeLike`` and a (mock) ``_BucketAdmin``.

    The ``ephemeral_postgres`` fixture is session-scoped; the schema
    is provisioned by the integration conftest with the APAP_WEB
    domain tables. We do NOT re-provision here; the test using this
    client must declare the ``ephemeral_postgres`` fixture (the
    conftest provides it for any test in the integration package).

    The conftest's ``_EphemeralPostgres.execute`` already returns
    ``list[dict[str, Any]]`` which matches the SQL protocol. The
    bucket methods are no-ops with a minimal shape that satisfies
    ``migration.bootstrap`` without performing any real storage
    operation: Postgres has no S3-compatible storage, and the
    E2E atom is focused on the SQL flow.

    The shape returned by ``get_bucket`` / ``ensure_bucket`` mirrors
    what the production InsForge client returns: a dict with
    ``name`` and ``isPublic`` keys (and ``files`` for ``get_bucket``).
    """

    def __init__(self, ephemeral_postgres: Any) -> None:
        self._ep = ephemeral_postgres
        self._buckets: dict[str, dict[str, Any]] = {}

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._ep.execute(query, params)

    # --- _BucketAdmin surface (no-op in Postgres fallback) ---

    def get_bucket(self, bucket_name: str) -> dict[str, Any] | None:
        return self._buckets.get(bucket_name)

    def ensure_bucket(
        self,
        bucket_name: str,
        *,
        is_public: bool = False,
    ) -> dict[str, Any]:
        bucket = {"name": bucket_name, "isPublic": is_public, "files": 0}
        self._buckets[bucket_name] = bucket
        return bucket


class InsForgeBackendClient:
    """Adapter that uses the production ``LocalPostgresExecutor``.

    This is the same code path that runs in production — the E2E
    atom exercises the actual production client against a real
    InsForge project. The ``INSFORGE_URL`` and ``INSFORGE_API_KEY``
    env vars configure the connection.

    The CI integration job supplies both env vars via the
    ``insforge`` service in ``.github/workflows/ci.yml``. Local
    runs without these env vars fall back to the Postgres backend
    in the test atom itself; the E2E atom does not silently
    default to InsForge.
    """

    def __init__(self, url: str, api_key: str) -> None:
        # Lazy import so test modules that use the Postgres backend
        # do not pay the cost of importing the production client.
        from app.core.local_backend.db import LocalPostgresExecutor

        self._client = LocalPostgresExecutor(url, api_key)

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._client.execute_sql(query, params)


def get_insforge_credentials() -> tuple[str, str] | None:
    """Read the InsForge connection from the environment.

    Returns ``(url, api_key)`` or ``None`` if either is missing.
    The function exists so the test atom has a single place to
    look up the env vars; later changes (e.g. reading from a
    config file) are localised here.
    """
    url = os.environ.get("APAP_INSFORGE_URL") or os.environ.get("INSFORGE_URL")
    key = os.environ.get(
        "APAP_INSFORGE_SERVICE_KEY"
    ) or os.environ.get("INSFORGE_API_KEY")
    if not url or not key:
        return None
    return url, key
