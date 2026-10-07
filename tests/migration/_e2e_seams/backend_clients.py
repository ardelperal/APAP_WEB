"""Test seam: real-backend clients that satisfy the migration _LocalBackendLike protocol.

This module lets the E2E migration tests run ``apply_legacy_to_web`` and
``apply_web_to_legacy`` against an ephemeral Postgres schema rather than
the FakeLocalBackend in-memory shim used by the rest of the migration suite.

The seam wraps existing clients:

  * ``PostgresBackendClient`` wraps the production ``LocalPostgresExecutor``
    with the E2E fixture's DSN and ephemeral schema. The schema has the
    APAP_WEB domain tables (animales, voluntarios, entradas, etc.) plus
    the catalogos (catalogos_motivos, catalogos_origenes, etc.) and
    the web-only feature shadow state table. Migrations need the
    catalogos to resolve the contrato type FK, so we seed them.

The E2E atom uses only the isolated Postgres client, so an operator DSN
cannot redirect it to a non-ephemeral database.
"""

from __future__ import annotations

from typing import Any, Protocol


class LocalBackendLike(Protocol):
    """Structural type satisfied by the isolated backend client.

    Mirrors the migration ``_LocalBackendLike`` protocol in
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
    """Expose the production executor on an ephemeral test schema.

    The E2E fixture provisions the schema before constructing this client.
    Bucket methods are no-ops with a minimal shape that satisfies
    ``migration.bootstrap`` without performing any real storage
    operation: Postgres has no S3-compatible storage, and the
    E2E atom is focused on the SQL flow.

    The shape returned by ``get_bucket`` / ``ensure_bucket`` mirrors
    what the production LocalBackend client returns: a dict with
    ``name`` and ``isPublic`` keys (and ``files`` for ``get_bucket``).
    """

    def __init__(self, dsn: str, schema: str) -> None:
        from app.core.local_backend.db import LocalPostgresExecutor

        self._executor = LocalPostgresExecutor(dsn, search_path=schema)
        self._buckets: dict[str, dict[str, Any]] = {}

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._executor.execute_sql(query, params)

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
