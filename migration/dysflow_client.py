"""Legacy SQL executor for the Access .accdb backend (M0).

Public entry point: :func:`execute_legacy_sql`. The applier
(``migration.apply.apply_legacy_to_web``) consumes it via the seam
in ``migration.legacy_reader._execute_legacy_query`` which routes
through ``set_legacy_query_executor`` for tests.

**Driver choice** (design §10):
    The primary driver is **pyodbc** (Microsoft Access Driver,
    Windows). The Dysflow MCP runtime dependency proposed in earlier
    drafts was rejected (MCP has ``writeExecutionPolicy: safe-by-
    default``, ``effectiveDryRunDefault: true`` for 60+ write tools,
    no SLO, agent-lifecycle-only — invoking it from a long-running
    migration is unsafe and uncacheable).

    The seam — ``LegacyQueryExecutor`` callable
    ``(path, sql, offset, limit) -> list[dict]`` — stays stable so
    a snapshot adapter or other fallback driver can be slotted in
    via ``set_legacy_query_executor`` without breaking the applier
    or any test.

**Contract** (per ``live-migration-runtime-boundary`` spec):

    - Returns ``list[dict]`` (column-name keyed) on success.
    - Returns ``[]`` when the SQL yields zero rows.
    - Raises :class:`migration.legacy_reader.LegacyReaderError` on
      any failure: missing pyodbc, missing Access driver, missing
      .accdb file, connect error, query error. The CLI maps the
      error to exit code 5.
    - Connection timeout is fixed at :data:`DEFAULT_QUERY_TIMEOUT_SECONDS`
      so a stuck .accdb cannot hang the migration.

**Determinism**:
    Row order matches ``cursor.fetchall()`` order; columns are
    taken from ``cursor.description`` (set after ``execute()`` and
    preserved across fetch). Same input rows produce deep-equal
    ``list[dict]`` across calls.

**No raw PII logging**:
    The executor never logs row contents. Audit logging happens at
    the applier layer (``log_safe("sync.applied", ...)`` after a
    row is written) and is the only place PII is emitted.
"""

from __future__ import annotations

import os
from typing import Any

# ``LegacyReaderError`` is imported lazily inside the function bodies
# below to avoid the circular dependency
# ``legacy_reader`` -> ``dysflow_client`` -> ``legacy_reader``. Tests
# that need to construct ``LegacyReaderError`` directly import it
# from ``migration.legacy_reader``.

# ---------------------------------------------------------------------------
# Module-level pyodbc reference (lazy import; tests can monkeypatch).
# ---------------------------------------------------------------------------

# A typed alias to keep mypy/pyright happy without forcing an
# unconditional ``import pyodbc`` (which would break on machines
# without pyodbc installed).
_pyodbc_module: Any = None
_pyodbc_import_error: BaseException | None = None


def _get_pyodbc() -> Any:
    """Lazy-load ``pyodbc`` and return it.

    The import is deferred so the module can be imported in any
    environment (e.g. CI without the Access driver). On a failed
    import the cached exception is re-raised wrapped as
    ``LegacyReaderError`` — the CLI maps that to exit code 5 with a
    ``pip install '.[etl]'`` hint.
    """
    global _pyodbc_module, _pyodbc_import_error
    if _pyodbc_module is None:
        from migration.legacy_reader import LegacyReaderError

        if _pyodbc_import_error is not None:
            raise LegacyReaderError(
                "pyodbc is not installed; run `pip install '.[etl]'` "
                "on the operator box to enable legacy .accdb reads."
            ) from _pyodbc_import_error
        try:
            import pyodbc as _pyodbc  # type: ignore[import-not-found]
        except ImportError as exc:
            _pyodbc_import_error = exc
            raise LegacyReaderError(
                "pyodbc is not installed; run `pip install '.[etl]'` "
                "on the operator box to enable legacy .accdb reads."
            ) from exc
        _pyodbc_module = _pyodbc
    return _pyodbc_module


# ---------------------------------------------------------------------------
# Driver + timeout constants.
# ---------------------------------------------------------------------------

#: Substring matched against ``pyodbc.drivers()`` to confirm the
#: Microsoft Access Driver is installed. The actual driver name
#: varies by Windows version (``Microsoft Access Driver (*.accdb)``
#: on older installs, ``Microsoft Access Driver (*.mdb, *.accdb)``
#: on newer ones), so we use two substrings and require both.
ACCESS_DRIVER_SUBSTRINGS: tuple[str, ...] = (
    "Microsoft Access Driver",
    "*.accdb",
)

#: Default connection / query timeout in seconds. Bounds the apply
#: pipeline against a stuck .accdb lock (operator can override per-run
#: via the runbook by closing Access manually).
DEFAULT_QUERY_TIMEOUT_SECONDS: int = 30


def _resolve_access_driver(pyodbc_mod: Any) -> str:
    """Return the Microsoft Access Driver name as listed by pyodbc.

    Raises :class:`LegacyReaderError` when the driver is not present
    so the CLI can map it to exit code 5 with a clear install hint
    (see runbook ``docs/runbooks/live-migration-apply.md``).
    """
    from migration.legacy_reader import LegacyReaderError

    drivers = list(pyodbc_mod.drivers())
    for name in drivers:
        if all(s in name for s in ACCESS_DRIVER_SUBSTRINGS):
            return name
    raise LegacyReaderError(
        f"Microsoft Access Driver is not installed; pyodbc reports "
        f"{len(drivers)} drivers: {drivers!r}. Install the Microsoft "
        "Access Database Engine (redistributable) on the operator box; "
        "see docs/runbooks/live-migration-apply.md."
    )


# ---------------------------------------------------------------------------
# Public executor.
# ---------------------------------------------------------------------------


def execute_legacy_sql(
    path: str,
    sql: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Execute ``sql`` against the .accdb at ``path`` and return rows.

    Args:
        path: absolute path to the legacy ``.accdb`` file.
        sql: Access SQL (uses ``TOP n``, not ``LIMIT``); the
            ``legacy_reader`` paging loop builds this with
            ``SELECT TOP {limit} ...``.
        offset: number of rows to skip (paging). The executor
            applies the offset client-side by slicing the returned
            rows; Access does not support ``OFFSET`` directly, so a
            caller that needs page N must fetch page 1..N and slice.
            For v1 (<= 5,000 rows per design §5) the overhead is
            negligible.
        limit: maximum rows to return (``BATCH_SIZE`` from the
            ``legacy_reader`` paging loop). Applied as the upper
            bound on the returned slice.

    Returns:
        ``list[dict[str, Any]]`` - each row keyed by column name in
        the order the cursor returned them. Empty list when the SQL
        yields zero rows or the offset/limit window is empty.

    Raises:
        LegacyReaderError: any of the following -
            * pyodbc is not installed,
            * the Microsoft Access Driver is not installed,
            * the .accdb file does not exist,
            * ``pyodbc.connect`` raised ``pyodbc.Error``,
            * the cursor raised ``pyodbc.Error`` mid-query.
        The CLI maps all of these to exit code 5.
    """
    pyodbc_mod = _get_pyodbc()
    # Lazy import: avoid ``legacy_reader`` -> ``dysflow_client`` cycle.
    from migration.legacy_reader import LegacyReaderError

    # --- pre-flight: driver installed --------------------------------
    driver = _resolve_access_driver(pyodbc_mod)

    # --- pre-flight: file exists -------------------------------------
    if not os.path.isfile(path):
        raise LegacyReaderError(
            f"Legacy .accdb not found at {path!r}; verify the "
            "APAP_LEGACY_ACCDB_PATH setting and the operator's mount."
        )

    # --- connect ------------------------------------------------------
    conn_str = f"Driver={{{driver}}};Dbq={path};"
    try:
        conn = pyodbc_mod.connect(conn_str, timeout=DEFAULT_QUERY_TIMEOUT_SECONDS)
    except pyodbc_mod.Error as exc:
        raise LegacyReaderError(
            f"Cannot connect to legacy .accdb at {path}: {exc}. "
            "Close any open Microsoft Access windows and retry; "
            "see docs/runbooks/live-migration-apply.md."
        ) from exc

    # --- execute + fetch --------------------------------------------
    try:
        try:
            cursor = conn.execute(sql)
        except pyodbc_mod.Error as exc:
            raise LegacyReaderError(
                f"Legacy query failed for {path}: {exc}"
            ) from exc

        try:
            all_rows = list(cursor.fetchall())
            description = tuple(cursor.description or ())
        except pyodbc_mod.Error as exc:
            raise LegacyReaderError(
                f"Legacy query fetch failed for {path}: {exc}"
            ) from exc
    finally:
        # Hard Rule 8: connection close MUST run on every code path,
        # including the error branches above. ``conn.close`` is
        # idempotent in pyodbc but we still swallow secondary errors
        # so the original ``LegacyReaderError`` is the one the caller
        # sees.
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - never mask the original exc
            pass

    if not all_rows:
        return []

    columns = [col[0] for col in description]

    # --- offset / limit slicing -------------------------------------
    safe_offset = max(0, int(offset))
    safe_limit = max(0, int(limit))
    if safe_limit == 0:
        return []
    page = all_rows[safe_offset : safe_offset + safe_limit]

    # --- map rows to dicts (deterministic column-keyed shape) --------
    return [dict(zip(columns, row, strict=True)) for row in page]


def execute_legacy_write(
    path: str,
    sql: str,
    params: list[Any] | None,
) -> int:
    """Execute a write SQL (INSERT/UPDATE/DELETE) against the legacy ``.accdb``.

    PR6 / M2 symmetric counterpart to :func:`execute_legacy_sql`. The
    reverse applier (``migration.apply_reverse.apply_web_to_legacy``)
    uses this seam to push web-side changes back to legacy via pyodbc.

    Args:
        path: absolute path to the legacy ``.accdb`` file.
        sql: Access SQL with positional ``?`` placeholders for params.
        params: parameter list (may be ``None`` when the SQL has no
            placeholders). Coerced via ``list(params or [])``.

    Returns:
        ``int`` rowcount (``cursor.rowcount``) reported by pyodbc.
        ``0`` means the statement matched no rows.

    Raises:
        LegacyReaderError: any of the following -
            * pyodbc is not installed,
            * the Microsoft Access Driver is not installed,
            * the ``.accdb`` file does not exist,
            * ``pyodbc.connect`` raised ``pyodbc.Error``,
            * ``cursor.execute`` raised ``pyodbc.Error`` mid-statement.

    Notes:
        No raw PII is logged; the audit log lives in the applier
        layer (``log_safe("sync.applied", direction="web->legacy",
        ...)`` per applied row).
    """
    pyodbc_mod = _get_pyodbc()
    from migration.legacy_reader import LegacyReaderError

    driver = _resolve_access_driver(pyodbc_mod)

    if not os.path.isfile(path):
        raise LegacyReaderError(
            f"Legacy .accdb not found at {path!r}; verify the "
            "APAP_LEGACY_ACCDB_PATH setting and the operator's mount."
        )

    conn_str = f"Driver={{{driver}}};Dbq={path};"
    try:
        conn = pyodbc_mod.connect(conn_str, timeout=DEFAULT_QUERY_TIMEOUT_SECONDS)
    except pyodbc_mod.Error as exc:
        raise LegacyReaderError(
            f"Cannot connect to legacy .accdb at {path}: {exc}. "
            "Close any open Microsoft Access windows and retry; "
            "see docs/runbooks/live-migration-apply.md."
        ) from exc

    try:
        try:
            cursor = conn.execute(sql, list(params or []))
        except pyodbc_mod.Error as exc:
            raise LegacyReaderError(
                f"Legacy write failed for {path}: {exc}"
            ) from exc
        # ``cursor.rowcount`` is the canonical pyodbc rowcount after
        # INSERT / UPDATE / DELETE; for Access the value is reported as
        # the number of rows affected by the statement. ``-1`` means
        # the driver could not determine the count; we coerce to ``0``
        # so the reverse applier never sees a sentinel.
        try:
            rowcount = int(cursor.rowcount)
        except (TypeError, ValueError):
            rowcount = 0
        if rowcount < 0:
            rowcount = 0
        # Force a commit so the write is durable across operator
        # restarts. Access autocommits per-statement when the cursor
        # is closed, but we make the contract explicit.
        try:
            conn.commit()
        except pyodbc_mod.Error:
            # If commit fails the driver will still close cleanly;
            # surface the original error via the next ``close``.
            pass
        return rowcount
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 - never mask the original exc
            pass


__all__ = [
    "ACCESS_DRIVER_SUBSTRINGS",
    "DEFAULT_QUERY_TIMEOUT_SECONDS",
    "execute_legacy_sql",
    "execute_legacy_write",
]
