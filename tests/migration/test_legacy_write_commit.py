"""Commit-durability atoms for ``migration.legacy_access_client`` (issue #218).

The bug reported in issue #218: ``execute_legacy_write`` did
``except pyodbc_mod.Error: pass`` on the ``conn.commit()`` call.
When the commit failed, the original rowcount was returned anyway,
so the operator saw ``applied`` while the write was actually rolled
back. The per-row ``log_safe("sync.applied", ...)`` audit log fired
with ``op="UPDATE"`` regardless of the commit outcome.

This module pins the new contract:

1. A failing ``conn.commit()`` propagates as a typed
   :class:`LegacyWriteCommitFailed` exception (NOT swallowed, NOT
   returned as success).
2. :class:`LegacyWriteCommitFailed` is a subclass of
   :class:`LegacyReaderError` so the existing CLI handler at
   ``migration.cli_apply_reverse.run_apply`` catches it via the
   ``except LegacyReaderError`` clause and surfaces exit 5
   (``legacy_read_failed`` categorical reason).
3. The per-row ``sync.applied`` audit log fires ONLY after a
   successful commit — the reverse applier
   (``migration.reverse_apply.per_row._reverse_apply_one_row``)
   issues the log AFTER the write seam returns, so a raised
   ``LegacyWriteCommitFailed`` interrupts the row before the log
   call.
4. The CLI exits non-zero when the commit fails (the orchestrator's
   per-row guard lets ``LegacyWriteCommitFailed`` propagate so the
   orchestrator raises to the CLI handler; the CLI handler maps it
   to exit 5).

Hard Rules honoured (web-tdd-philosophy):

- **Rule 1 (fixture gate)**: every atom builds its own fake pyodbc
  with the failure mode it wants to exercise; no shared state
  across tests.
- **Rule 2 (DI)**: the pyodbc module is injected via ``monkeypatch``
  on ``legacy_access_client._pyodbc_module`` (the same seam the
  existing ``test_runtime_boundary.py`` atoms use).
- **Rule 4 (no humo)**: every assertion is on the actual exception
  class, message, or chained ``__cause__`` — never "no error".
- **Rule 5 (three paths)**: happy (commit succeeds) + sad (commit
  raises) + edge (commit raises after a successful ``cursor.execute``).
- **Rule 8 (no production mutation)**: the fake pyodbc never opens
  a real ``.accdb``; only the executor's row-raising path is
  monkeypatched.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from migration import legacy_access_client
from migration.legacy_access_client import (
    LegacyWriteCommitFailed,
    LegacyWriteRowcountUnknownError,
    execute_legacy_write,
)
from migration.legacy_reader import LegacyReaderError

# ---------------------------------------------------------------------------
# Test scaffolding — minimal fake pyodbc that exercises the commit seam.
# ---------------------------------------------------------------------------


class _FakePyodbcError(Exception):
    """Stand-in for ``pyodbc.Error`` used by the commit-failure fakes.

    ``execute_legacy_write`` does ``except pyodbc_mod.Error``; the
    fake must expose a class the production code's ``except`` clause
    catches. We define it as a plain ``Exception`` subclass and bind
    it to the fake module's ``Error`` attribute so the production
    ``isinstance(exc, pyodbc_mod.Error)`` check passes.
    """


class _CommitFailingCursor:
    """Cursor whose ``rowcount`` is ``1`` (success) but whose
    parent connection's ``commit()`` raises ``pyodbc.Error``.

    The production code:

    1. ``cursor.execute(sql, params)`` — does NOT raise here.
    2. ``cursor.rowcount`` — returns ``1`` (a real write count).
    3. ``conn.commit()`` — raises (the durability gap).
    4. ``conn.close()`` — always runs in the ``finally`` block.

    The fake also tracks every call so tests can assert the
    contract: ``execute`` ran, ``commit`` ran, ``close`` ran
    (Hard Rule 8: no resource leak).
    """

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.executed: list[str] = []

    def execute(self, _sql: str, _params: list[Any]) -> _CommitFailingCursor:
        self.executed.append(_sql)
        return self


class _CommitFailingConnection:
    """Connection whose ``commit()`` raises ``pyodbc.Error`` and
    whose ``close()`` is tracked for Hard Rule 8 invariants.
    """

    def __init__(self, cursor: _CommitFailingCursor, pyodbc_error: type[BaseException]) -> None:
        self._cursor = cursor
        self._pyodbc_error = pyodbc_error
        self.closed = False
        self.committed = False

    def execute(self, sql: str, params: list[Any]) -> _CommitFailingCursor:
        return self._cursor.execute(sql, params)

    def commit(self) -> None:
        self.committed = True
        raise self._pyodbc_error("disk full during fsync")

    def close(self) -> None:
        self.closed = True


class _CommitFailingPyodbc:
    """Pyodbc stand-in that ALWAYS raises on ``commit()``.

    The fake exposes ``Error`` as the class used in the
    ``isinstance`` check, so the production ``except pyodbc_mod.Error``
    block catches the exception.

    Default ``rowcount=1`` — the production path reaches the
    commit step before the rowcount=-1 check.
    """

    Error = _FakePyodbcError

    def __init__(self, pyodbc_error: type[BaseException] | None = None) -> None:
        self._pyodbc_error = pyodbc_error or _FakePyodbcError
        self.connections: list[_CommitFailingConnection] = []
        self.cursors: list[_CommitFailingCursor] = []

    def drivers(self) -> list[str]:
        return ["Microsoft Access Driver (*.accdb)"]

    def connect(self, _conn_str: str, *, timeout: int) -> _CommitFailingConnection:
        cursor = _CommitFailingCursor(rowcount=1)
        self.cursors.append(cursor)
        conn = _CommitFailingConnection(cursor, self._pyodbc_error)
        self.connections.append(conn)
        return conn


@pytest.fixture
def existing_accdb(tmp_path: Path) -> str:
    """A real file the executor can find at connect time.

    The fake ``connect`` does not actually open the file; the test
    uses an existing path to validate the ``isfile`` pre-flight
    passes.
    """
    p = tmp_path / "legacy.accdb"
    p.write_bytes(b"\x00\x01\x02")
    return str(p)


@pytest.fixture
def install_commit_failing_pyodbc(
    monkeypatch: pytest.MonkeyPatch,
) -> _CommitFailingPyodbc:
    """Install the commit-failing fake pyodbc into the executor.

    Mirrors the ``fake_pyodbc_factory`` pattern in
    ``test_runtime_boundary.py`` so the test seam is consistent
    across the migration test suite.
    """
    fake = _CommitFailingPyodbc()
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(legacy_access_client, "_pyodbc_module", fake)
    return fake


# ---------------------------------------------------------------------------
# 1. Type contract — LegacyWriteCommitFailed is a LegacyReaderError subclass
# ---------------------------------------------------------------------------


def test_legacy_write_commit_failed_is_subclass_of_legacy_reader_error() -> None:
    """The new typed exception MUST be a subclass of
    :class:`LegacyReaderError`.

    The CLI handler (``migration.cli_apply_reverse.run_apply``) catches
    :class:`LegacyReaderError` and maps it to exit 5 —
    ``legacy_read_failed``. Subclassing means the CLI handler
    transparently catches the new commit-failure case without a
    separate ``except`` clause.
    """
    assert issubclass(LegacyWriteCommitFailed, LegacyReaderError)
    assert LegacyWriteCommitFailed is not LegacyReaderError


# ---------------------------------------------------------------------------
# 2. Sad — conn.commit() failure → LegacyWriteCommitFailed (NOT swallowed)
# ---------------------------------------------------------------------------


def test_execute_legacy_write_raises_legacy_write_commit_failed_on_commit_failure(
    install_commit_failing_pyodbc: _CommitFailingPyodbc,
    existing_accdb: str,
) -> None:
    """A failing ``conn.commit()`` MUST raise ``LegacyWriteCommitFailed``.

    Issue #218 acceptance: ``A failing conn.commit() propagates as a
    typed error to the CLI handler``. The previous behaviour
    (``except pyodbc_mod.Error: pass``) silently swallowed the
    failure and returned the rowcount as success — this atom pins
    the new exception contract.
    """
    with pytest.raises(LegacyWriteCommitFailed) as excinfo:
        execute_legacy_write(
            existing_accdb,
            "UPDATE TbVoluntarios SET Email = ? WHERE Voluntario = ?",
            ["new@x", "alice"],
        )

    # The exception message MUST mention the commit failure so the
    # operator can diagnose from the Categorical line.
    assert "commit" in str(excinfo.value).lower()
    # And the chained cause MUST be the original pyodbc.Error so the
    # ``__cause__`` carries the diagnostic upstream.
    assert isinstance(excinfo.value.__cause__, _FakePyodbcError)


# ---------------------------------------------------------------------------
# 3. Sad — the connection is closed even when commit fails
# ---------------------------------------------------------------------------


def test_execute_legacy_write_closes_connection_on_commit_failure(
    install_commit_failing_pyodbc: _CommitFailingPyodbc,
    existing_accdb: str,
) -> None:
    """Hard Rule 8: the connection MUST close even on the commit
    failure path.

    The previous ``except pyodbc_mod.Error: pass`` swallowed the
    failure; the connection was closed in the ``finally`` block, so
    no leak. The new typed re-raise must preserve that invariant —
    a regression that skips ``close()`` would leak a pyodbc
    connection on every commit failure.
    """
    with pytest.raises(LegacyWriteCommitFailed):
        execute_legacy_write(
            existing_accdb,
            "UPDATE TbVoluntarios SET Email = ? WHERE Voluntario = ?",
            ["new@x", "alice"],
        )

    assert len(install_commit_failing_pyodbc.connections) == 1
    assert install_commit_failing_pyodbc.connections[0].closed is True


# ---------------------------------------------------------------------------
# 4. Sad — commit fails BEFORE the rowcount=-1 check runs
# ---------------------------------------------------------------------------


def test_execute_legacy_write_does_not_swallow_commit_in_favour_of_rowcount(
    install_commit_failing_pyodbc: _CommitFailingPyodbc,
    existing_accdb: str,
) -> None:
    """Commit failure MUST be raised — not converted into a
    rowcount-based error.

    The previous code path:

    1. ``cursor.execute`` — succeeds.
    2. ``int(cursor.rowcount)`` — returns ``1``.
    3. ``conn.commit()`` — raises.
    4. ``except pyodbc_mod.Error: pass`` — swallowed.
    5. ``if rowcount == -1: raise LegacyWriteRowcountUnknownError`` — not reached.
    6. ``return rowcount`` — success returned.

    The new code raises ``LegacyWriteCommitFailed`` AT step 4, so
    the rowcount-driven ``LegacyWriteRowcountUnknownError`` path is
    never reached for this scenario. A regression that re-orders
    the checks and raises ``LegacyWriteRowcountUnknownError``
    instead would lose the commit-failure semantics.
    """
    with pytest.raises(LegacyWriteCommitFailed) as excinfo:
        execute_legacy_write(
            existing_accdb,
            "UPDATE TbVoluntarios SET Email = ? WHERE Voluntario = ?",
            ["new@x", "alice"],
        )

    assert not isinstance(excinfo.value, LegacyWriteRowcountUnknownError)


# ---------------------------------------------------------------------------
# 5. Happy — successful commit returns rowcount (regression guard)
# ---------------------------------------------------------------------------


class _HappyCursor:
    rowcount = 1

    def execute(self, _sql: str, _params: list[Any]) -> _HappyCursor:
        return self


class _HappyConnection:
    closed = False
    committed = False

    def execute(self, sql: str, params: list[Any]) -> _HappyCursor:
        return _HappyCursor().execute(sql, params)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class _HappyPyodbc:
    Error = _FakePyodbcError

    def __init__(self) -> None:
        self.connections: list[_HappyConnection] = []

    def drivers(self) -> list[str]:
        return ["Microsoft Access Driver (*.accdb)"]

    def connect(self, _conn_str: str, *, timeout: int) -> _HappyConnection:
        conn = _HappyConnection()
        self.connections.append(conn)
        return conn


def test_execute_legacy_write_returns_rowcount_on_successful_commit(
    monkeypatch: pytest.MonkeyPatch, existing_accdb: str
) -> None:
    """``Happy path — commit succeeds — rowcount returned.

    Regressions that over-caught the commit failure (e.g. raising
    on every call) would break the existing PR6 reverse applier
    pipeline. This atom pins the happy path so a future
    over-tightening of the commit failure check is caught.
    """
    fake = _HappyPyodbc()
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(legacy_access_client, "_pyodbc_module", fake)

    rowcount = execute_legacy_write(
        existing_accdb,
        "UPDATE TbVoluntarios SET Email = ? WHERE Voluntario = ?",
        ["new@x", "alice"],
    )

    assert rowcount == 1
    assert fake.connections[0].closed is True
    assert fake.connections[0].committed is True


# ---------------------------------------------------------------------------
# 6. End-to-end — log_safe("sync.applied") does NOT fire on commit failure
# ---------------------------------------------------------------------------


def test_apply_web_to_legacy_does_not_emit_sync_applied_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When the write seam raises ``LegacyWriteCommitFailed``, the
    per-row ``sync.applied`` audit log MUST NOT fire.

    Issue #218 acceptance: ``The sync.applied audit log fires ONLY
    on successful commit.`` The audit log lives in
    :func:`migration.reverse_apply.per_row._reverse_apply_one_row`
    AFTER the write seam returns. A raised ``LegacyWriteCommitFailed``
    interrupts the row before the log call.

    Atom layout:

    1. Build a web row whose legacy key is missing → INSERT path.
    2. Inject a write seam that raises ``LegacyWriteCommitFailed``
       (the new typed exception).
    3. Capture every ``log_safe`` call.
    4. Assert ``sync.applied`` is NOT in the captured events.
    """
    import app.core.logging as logging_mod
    from migration import legacy_reader
    from migration.apply_reverse import _reverse_apply_one_row
    from migration.mappings import load_mapping
    from tests.migration.conftest import FakeInsForge

    captured: list[dict[str, Any]] = []

    def _capture(event: str, **fields: object) -> None:
        captured.append({"event": event, **fields})

    monkeypatch.setattr(logging_mod, "log_safe", _capture)

    monkeypatch.setattr(legacy_reader, "_legacy_query_executor", None)
    monkeypatch.setattr(legacy_reader, "_legacy_write_executor", None)

    def _explode_write(
        _path: str, _sql: str, _params: list[Any] | None
    ) -> int:
        raise LegacyWriteCommitFailed("disk full during fsync")

    legacy_reader.set_legacy_query_executor(
        lambda *_args, **_kwargs: []
    )
    legacy_reader.set_legacy_write_executor(_explode_write)
    try:
        client = FakeInsForge()
        client.seed(
            "voluntarios",
            [{"voluntario": "alice", "email": "new@x", "tel1": None, "tel2": None}],
        )
        mapping = load_mapping("voluntario")
        # The exception is expected to propagate because the per-row
        # guard in ``apply_web_to_legacy`` raises
        # ``LegacyWriteCommitFailed`` (categorical, not per-row).
        with pytest.raises(LegacyWriteCommitFailed):
            _reverse_apply_one_row(
                client=client,  # type: ignore[arg-type]
                mapping=mapping,
                web_row={"voluntario": "alice", "email": "new@x"},
                legacy_path=str(tmp_path / "legacy.accdb"),
                _legacy_columns=tuple(
                    c.legacy_column
                    for c in mapping.columns
                    if c.legacy_column
                ),
                web_table="voluntarios",
                dry_run=False,
                legacy_by_key={},
                dni_collision_counter=None,
            )
    finally:
        legacy_reader.set_legacy_query_executor(None)
        legacy_reader.set_legacy_write_executor(None)

    sync_applied = [c for c in captured if c.get("event") == "sync.applied"]
    assert sync_applied == [], (
        "sync.applied fired despite a LegacyWriteCommitFailed from the "
        f"write seam; captured events: {captured!r}"
    )


# ---------------------------------------------------------------------------
# 7. End-to-end — CLI exits non-zero (exit 5 categorical) on commit failure
# ---------------------------------------------------------------------------


def test_apply_web_to_legacy_propagates_legacy_write_commit_failed_to_caller(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ``LegacyWriteCommitFailed`` from the write seam MUST propagate
    to the caller of ``apply_web_to_legacy``.

    The CLI handler (``migration.cli_apply_reverse.run_apply``) is
    the caller; it catches ``LegacyReaderError`` and exits 5
    (``legacy_read_failed``). Because
    :class:`LegacyWriteCommitFailed` subclasses
    :class:`LegacyReaderError`, the handler catches it transparently.

    The orchestrator's per-row guard in
    ``migration.reverse_apply.orchestrator`` lets
    ``LegacyWriteCommitFailed`` propagate (a categorical failure,
    not a per-row error) so the CLI handler sees the full
    exception. This atom pins that propagation contract.
    """
    from migration import legacy_reader
    from migration.apply_reverse import apply_web_to_legacy
    from tests.migration.conftest import FakeInsForge

    monkeypatch.setattr(legacy_reader, "_legacy_query_executor", None)
    monkeypatch.setattr(legacy_reader, "_legacy_write_executor", None)

    def _explode_write(
        _path: str, _sql: str, _params: list[Any] | None
    ) -> int:
        raise LegacyWriteCommitFailed("disk full during fsync")

    legacy_reader.set_legacy_query_executor(
        lambda *_args, **_kwargs: []
    )
    legacy_reader.set_legacy_write_executor(_explode_write)
    try:
        client = FakeInsForge()
        client.seed(
            "voluntarios",
            [{"voluntario": "alice", "email": "new@x", "tel1": None, "tel2": None}],
        )
        with pytest.raises(LegacyWriteCommitFailed) as excinfo:
            apply_web_to_legacy(
                client,  # type: ignore[arg-type]
                "voluntario",
                legacy_path=str(tmp_path / "legacy.accdb"),
                web_snapshot=None,
                dry_run=False,
                lock_path=tmp_path / "migration.lock",
            )
    finally:
        legacy_reader.set_legacy_query_executor(None)
        legacy_reader.set_legacy_write_executor(None)

    # The exception is a LegacyReaderError subclass → CLI handler
    # catches it via the ``except LegacyReaderError`` clause and
    # exits 5 with the ``legacy_read_failed`` categorical reason.
    assert isinstance(excinfo.value, LegacyReaderError)


__all__ = [
    "LegacyWriteCommitFailed",
]
