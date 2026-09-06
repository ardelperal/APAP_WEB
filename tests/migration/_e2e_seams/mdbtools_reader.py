"""Test seam: read a real .accdb via mdb-export for E2E migration tests.

This module is a **test seam only** — it lives under
``tests/migration/_e2e_seams/`` and is imported exclusively by the E2E
tests. Production code reads the .accdb via
``migration.legacy_access_client::execute_legacy_sql`` (pyodbc + Microsoft
Access Driver, Windows). D-31 of
``openspec/changes/live-data-migration-sandbox`` is preserved: mdbtools
is **not** used in production code.

Two roles:

  1. **Executor factory** (``install_mdbtools_executor``): the E2E atom
     builds a ``LegacyQueryExecutor``-compatible callable from
     mdb-export and installs it via
     ``migration.legacy_reader.set_legacy_query_executor(...)``. The
     production ``apply_legacy_to_web`` then reads the .accdb via
     mdbtools without touching the production pyodbc path. This is
     how the E2E atom exercises the full apply pipeline against a
     real .accdb.

  2. **Standalone reader** (``MdbToolsLegacyReader``): wraps mdb-export
     for the E2E atom to use directly (e.g. counting rows in a
     pre-apply snapshot, asserting a row landed in the destination
     table). Not all atoms need the executor factory — the simple
     ones just read the legacy side via this reader.

The seam is read-only: the E2E test creates a *copy* of the fixture
``.accdb`` in ``tmp_path``, mutates that copy, and asserts the mutation
result. The fixture in ``tests/migration/local-access/`` is never
touched.
"""

from __future__ import annotations

import csv
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class MdbToolsMissingError(RuntimeError):
    """mdb-export binary is not installed (or not on PATH)."""


class MdbToolsReadError(RuntimeError):
    """mdb-export failed; the .accdb is corrupted or unreadable."""


# ``migration.legacy_reader`` uses the SQL clause ``FROM <table>`` to
# identify the target table. mdb-export takes the table name as a
# positional argument, so we parse it out of the SQL the apply
# pipeline issues.
_FROM_RE = re.compile(
    r"\bFROM\s+[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)[`\"\]]?",
    re.IGNORECASE,
)


def _table_from_sql(sql: str) -> str:
    match = _FROM_RE.search(sql)
    if not match:
        raise MdbToolsReadError(
            f"Could not extract table name from SQL: {sql!r}"
        )
    return match.group(1)


def _export_table_csv(legacy_path: str, table: str) -> list[dict[str, str]]:
    """Run mdb-export and parse the resulting CSV into list of dicts.

    Returns string-typed rows. The migration code's mapping YAML
    coerces to the web column types; the seam is typed as ``str`` to
    match the production pyodbc behaviour for unrecognised types.
    """
    proc = subprocess.run(
        [
            "mdb-export",
            "-D", "%Y-%m-%d %H:%M:%S",
            "-d", ",",
            legacy_path,
            table,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        if proc.returncode == 127 or "command not found" in proc.stderr:
            raise MdbToolsMissingError(
                f"mdb-export not installed (failed for {table!r}). "
                "Install with: apt-get install mdbtools"
            )
        raise MdbToolsReadError(
            f"mdb-export failed for table {table!r} in {legacy_path!r}: "
            f"exit={proc.returncode} stderr={proc.stderr!r}"
        )
    reader = csv.DictReader(proc.stdout.splitlines())
    return list(reader)


def _make_executor(legacy_path: str):
    """Build a ``LegacyQueryExecutor``-compatible callable for the given .accdb.

    Returns a function ``(legacy_path_arg, sql, offset, limit) ->
    list[dict]`` that honours the contract
    ``migration.legacy_reader.set_legacy_query_executor`` expects.

    Pagination is simulated client-side: mdb-export does not support
    OFFSET/LIMIT (Access uses ``SELECT TOP n``), so we run mdb-export
    once per table and slice in memory. The cache is per-table per-call
    (the apply pipeline touches a bounded set of tables so the cache
    memory footprint is small).
    """
    cache: dict[str, list[dict[str, str]]] = {}

    def _executor(
        legacy_path_arg: str,
        sql: str,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        table = _table_from_sql(sql)
        if table not in cache:
            cache[table] = _export_table_csv(legacy_path, table)
        rows = cache[table]
        return rows[offset:offset + limit]

    return _executor


@contextmanager
def install_mdbtools_executor(legacy_path: str) -> Iterator[None]:
    """Install the mdbtools executor as the active legacy query executor.

    The seam is installed for the duration of the context. On exit,
    the executor is cleared (``set_legacy_query_executor(None)``) so
    the next test starts clean. Hard reset (not "restore previous")
    because the cross-test leakage policy in
    ``tests/migration/conftest.py`` requires the same.
    """
    from migration import legacy_reader

    legacy_reader.set_legacy_query_executor(_make_executor(legacy_path))
    try:
        yield
    finally:
        legacy_reader.set_legacy_query_executor(None)


class MdbToolsLegacyReader:
    """Standalone read-only reader for a real ``.accdb`` via mdb-export.

    Use this for atoms that do not need the full
    ``apply_legacy_to_web`` pipeline — e.g. counting rows in a
    pre-apply snapshot, asserting a specific row landed in the
    destination table by re-reading the legacy copy. The
    ``install_mdbtools_executor`` factory is the right choice for
    atoms that exercise the apply pipeline.
    """

    def __init__(self, legacy_path: str) -> None:
        self._path = legacy_path
        self._cache: dict[str, list[dict[str, str]]] = {}

    def read_table(self, table_name: str) -> list[dict[str, str]]:
        if table_name not in self._cache:
            self._cache[table_name] = _export_table_csv(self._path, table_name)
        return list(self._cache[table_name])

    def list_tables(self) -> list[str]:
        proc = subprocess.run(
            ["mdb-tables", "-1", self._path],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise MdbToolsReadError(
                f"mdb-tables failed for {self._path!r}: "
                f"exit={proc.returncode} stderr={proc.stderr!r}"
            )
        return [t for t in proc.stdout.splitlines() if t.strip()]


def require_mdbtools() -> None:
    """Skip the calling test if mdb-export / mdb-tables is not installed.

    The seam is a *test* dependency — CI Linux without mdbtools can
    skip the E2E atom rather than fail. The operator gets a clear
    message: install mdbtools and re-run.
    """
    try:
        subprocess.run(
            ["mdb-export", "-h"],
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            ["mdb-tables", "-h"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        import pytest

        pytest.skip(
            "mdb-export / mdb-tables is not installed; the E2E migration "
            "atom requires mdbtools. Install with: apt-get install mdbtools"
        )
