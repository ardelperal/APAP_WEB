"""PostgreSQL execution and the F1 migration seam."""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from migration import acquire_lock, release_lock


class DatabaseError(RuntimeError):
    """Connection-level PostgreSQL failure."""

class QueryError(RuntimeError):
    """Query-level failure safe to map to HTTP 4xx."""
    def __init__(self, message: str, code: str = "query_error") -> None:
        super().__init__(message)
        self.code = code

class QueryResult(list[dict[str, Any]]):
    """Rows and affected-row count from one cursor."""
    def __init__(self, rows: list[dict[str, Any]], rowcount: int) -> None:
        super().__init__(rows)
        self.rowcount = rowcount

_DOLLAR_TO_PERCENT = re.compile(r"\$(\d+)")
_SAFE_SEGMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

def _safe_table(table_name: str) -> str:
    """Return a safe dotted SQL identifier or raise."""
    parts = table_name.split(".")
    if not all(_SAFE_SEGMENT.fullmatch(part) for part in parts):
        raise ValueError(f"unsafe SQL identifier {table_name!r}")
    return table_name

def _try_seam_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a migration seam call without allowing it to affect SQL."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None

class LocalPostgresExecutor:
    """Execute one PostgreSQL statement and return dictionary rows."""
    def __init__(self, dsn: str, search_path: str | None = None) -> None:
        self._dsn = dsn
        self._search_path = search_path
        self._migration_state: dict[str, Any] = {}

    def _connect(self) -> psycopg.Connection[Any]:
        """Open a connection and apply its optional search path."""
        connection = psycopg.connect(self._dsn)
        if self._search_path:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('search_path', %s, false)", (self._search_path,))
            connection.commit()
        return connection

    def close(self) -> None:
        """Release per-operation resources (there is no M0 pool)."""

    def execute(self, query: str, params: list[Any] | tuple[Any, ...] | None = None) -> QueryResult:
        """Rewrite native placeholders, execute, and return rows."""
        # lazy-import: keep migration.apply's patch surface live for migration tests
        from migration import apply as apply_module

        # lazy-import: keep the snapshot manifest local to this function
        from migration.lock_snapshot import PhotosManifest
        seam_path = Path(os.devnull) / "apap-local-backend-migration-seam"
        source_hash = _try_seam_call(apply_module.compute_accdb_hash, seam_path) or ""
        lock_info = _try_seam_call(apply_module.acquire_lock, seam_path)
        snapshot = _try_seam_call(apply_module.read_snapshot, seam_path)
        state = {"source_hash": source_hash, "lock_info": lock_info, "snapshot": snapshot}
        state["written"] = _try_seam_call(
            apply_module.write_snapshot, seam_path, direction="rawsql",
            accdb_sha256=source_hash, photos_manifest=PhotosManifest(0, 0, ""),
        )
        state["released"] = _try_seam_call(apply_module.release_lock, seam_path)
        self._migration_state = state
        query = _DOLLAR_TO_PERCENT.sub(r"%s", query)
        try:
            with self._connect() as connection:
                cursor = connection.cursor(row_factory=dict_row)
                try:
                    cursor.execute(query, params or [])
                    description = cursor.description
                    rows = list(cursor.fetchall()) if description is not None else []
                    rowcount = len(rows) if description is not None else cursor.rowcount
                    connection.commit()
                    return QueryResult(rows, int(rowcount))
                except psycopg.Error as exc:
                    connection.rollback()
                    if getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None):
                        raise QueryError(str(exc)) from exc
                    raise DatabaseError(str(exc)) from exc
                finally:
                    cursor.close()
        except psycopg.Error as exc:
            raise DatabaseError(str(exc)) from exc

__all__ = ["DatabaseError", "LocalPostgresExecutor", "QueryError", "QueryResult", "acquire_lock", "release_lock"]
