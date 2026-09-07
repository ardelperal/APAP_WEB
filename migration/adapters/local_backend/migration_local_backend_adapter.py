"""LocalBackend migration adapter.

Real implementation of ``migration.ports.web_reader_port.WebReaderPort`
and the migration ``SqlExecutor` Protocol against the LocalBackend
postgres backend.

The ``SqlExecutor` Protocol in ``migration.apply`` was broader than
needed in the LocalBackend world (it required ``get_bucket`` / ``ensure_bucket``
methods that the LocalBackend does not expose — buckets are a legacy
legacy concept that the LocalBackend does not implement). This
adapter provides the SQL surface only and lets the migration package
drop the bucket-related calls entirely.

Migration use cases that need the bucket surface (``check_private_bucket``
/ ``ensure_private_bucket``) are no longer invoked in the LocalBackend
world; the test fixtures for those code paths were deleted in #5's
clean-up. ``migration.cli_ensure_bucket`` becomes a no-op shim that
prints a deprecation notice and exits 0 (the CLI surface is preserved
for existing scripts).
"""

from __future__ import annotations

from typing import Any

from app.core.data_access import SqlExecutor
from app.core.local_backend.db import LocalPostgresExecutor


class LocalBackendMigrationAdapter:
    """Real ``SqlExecutor`` adapter against the LocalBackend postgres.

    Wraps a :class:`~app.core.local_backend.db.LocalPostgresExecutor` and
    exposes its ``execute_sql`` to the migration package. The class is
    deliberately a thin pass-through — the migration ``SqlExecutor`
    Protocol matches ``LocalPostgresExecutor`` structurally, so callers
    can pass either a real executor or this wrapper interchangeably.
    """

    def __init__(self, executor: LocalPostgresExecutor) -> None:
        self._executor = executor

    @property
    def executor(self) -> LocalPostgresExecutor:
        return self._executor

    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self._executor.execute_sql(query, params)


def build_migration_executor(
    dsn: str, *, search_path: str | None = None
) -> LocalPostgresExecutor:
    """Build a ``LocalPostgresExecutor`` for the migration package.

    Convenience factory used by both the CLI and the test fixtures. The
    DSN follows the production ``APAP_LOCAL_DB_URL`` shape (postgresql
    scheme, optional search_path query parameter).
    """
    return LocalPostgresExecutor(dsn, search_path=search_path)


__all__ = [
    "LocalBackendMigrationAdapter",
    "build_migration_executor",
    "SqlExecutor",
]
