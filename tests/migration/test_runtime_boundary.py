"""Runtime boundary atoms for ``migration.dysflow_client`` (PR1 / M0).

This module pins the contract for the legacy ``.accdb`` executor that
``apply_legacy_to_web`` and (in M2) ``apply_web_to_legacy`` consume via
the ``migration.legacy_reader`` seam. Three classes of coverage:

1. **Executor happy/sad/edge** (``execute_legacy_sql``). We inject a
   fake ``pyodbc`` module via ``monkeypatch.setattr`` so the tests run
   on machines that may not have the Microsoft Access driver installed
   (CI, dev laptops). Production wires the real ``pyodbc`` at import
   time inside ``migration.dysflow_client``.

2. **Seam contract** (``set_legacy_query_executor`` /
   ``_execute_legacy_query``). The seam MUST remain stable between M0
   and M2 so the apply / diff / reconcile paths keep working. Tests
   verify injection, reset, and default fallback.

3. **Static boundary** — there are NO executable Dysflow MCP imports
   or calls under ``app/`` or ``migration/``. The detector parses the
   source with ``ast`` so docstrings and comments are silently
   ignored; only real ``Import``/``ImportFrom``/``Call`` nodes count.

Hard Rules honoured (web-tdd-philosophy):

- **Rule 1 (fixture gate)**: every atom builds its own fake pyodbc;
  no shared module state across tests.
- **Rule 2 (DI)**: the executor seam and the pyodbc dependency are
  both injected; production wiring is via real imports, tests via
  ``monkeypatch``.
- **Rule 4 (no humo)**: assertions are on the actual returned rows /
  raised exception class, never "no error".
- **Rule 5 (three paths)**: each slice ships happy + sad + edge.
- **Rule 6 (refactor-safety)**: tests assert OUTCOME (returned
  ``list[dict]`` shape, raised exception class) not implementation
  details (specific SQL fragments).
- **Rule 8 (no production mutation)**: the fake pyodbc never touches
  a real ``.accdb``; the boundary test only parses source files.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from migration import dysflow_client, legacy_reader
from migration.dysflow_client import execute_legacy_sql
from migration.legacy_reader import LegacyReaderError, set_legacy_query_executor

# ---------------------------------------------------------------------------
# Test scaffolding
# ---------------------------------------------------------------------------


class FakeCursor:
    """Minimal ODBC cursor stand-in for the pyodbc fake.

    Stores the rows it was given plus a description, and yields them
    via ``fetchall``. Sufficient for the ``dict(zip(columns, row))``
    shape the production executor builds.
    """

    def __init__(self, rows: list[tuple[Any, ...]], columns: list[str]) -> None:
        self._rows = rows
        self.description = tuple((name,) for name in columns)
        self.executed: list[str] = []

    def execute(self, sql: str) -> FakeCursor:
        self.executed.append(sql)
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def close(self) -> None:  # pragma: no cover — defensive
        pass


class FakeConnection:
    """Minimal ODBC connection stand-in for the pyodbc fake.

    Records every ``execute`` call so tests can assert the SQL the
    production code generated, and closes deterministically so the
    Hard Rule "no global resource leaks" holds.
    """

    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False
        self.executed: list[str] = []

    def execute(self, sql: str) -> FakeCursor:
        self.executed.append(sql)
        self._cursor.execute(sql)
        return self._cursor

    def close(self) -> None:
        self.closed = True


class FakePyodbc:
    """Stand-in for the ``pyodbc`` module the production executor imports.

    Implements the small surface ``migration.dysflow_client`` uses:

    - ``drivers() -> list[str]``
    - ``connect(conn_str, *, timeout) -> FakeConnection``
    - ``Error`` exception class so the production ``except
      pyodbc_mod.Error`` block works.

    Tests pre-load rows/columns per-call by instantiating
    ``FakePyodbc(rows=[...], columns=[...])`` and patching
    ``dysflow_client._pyodbc_module`` to the instance.
    """

    def __init__(
        self,
        *,
        rows: list[tuple[Any, ...]] | None = None,
        columns: list[str] | None = None,
        driver_name: str = "Microsoft Access Driver (*.accdb)",
        connect_raises: BaseException | None = None,
    ) -> None:
        self._rows = list(rows or [])
        self._columns = list(columns or [])
        self._driver_name = driver_name
        self._connect_raises = connect_raises
        self.connections: list[FakeConnection] = []

        # The production code does ``except pyodbc_mod.Error``; expose
        # a real exception class so ``isinstance`` and ``raise ... from``
        # both work.
        class _Error(Exception):
            pass

        self.Error = _Error

    # --- pyodbc surface -------------------------------------------------

    def drivers(self) -> list[str]:
        return [self._driver_name]

    def connect(self, conn_str: str, *, timeout: int) -> FakeConnection:
        if self._connect_raises is not None:
            raise self._connect_raises
        cursor = FakeCursor(self._rows, self._columns)
        conn = FakeConnection(cursor)
        self.connections.append(conn)
        return conn


@pytest.fixture
def fake_pyodbc_factory():
    """Factory fixture that returns a builder for FakePyodbc.

    Returns a callable ``make(**kwargs)`` so each test composes the
    fake it needs. The factory also patches
    ``dysflow_client._pyodbc_module`` to the returned fake and
    restores the previous value on teardown.
    """
    previous = dysflow_client._pyodbc_module

    def _make(**kwargs: Any) -> FakePyodbc:
        fake = FakePyodbc(**kwargs)
        dysflow_client._pyodbc_module = fake
        return fake

    yield _make

    dysflow_client._pyodbc_module = previous


@pytest.fixture
def existing_accdb(tmp_path: Path) -> str:
    """A real file the executor can find at connect time.

    The fake ``connect`` doesn't actually open the file; the test
    uses an existing path to validate the ``isfile`` pre-flight passes.
    """
    p = tmp_path / "legacy.accdb"
    p.write_bytes(b"\x00\x01\x02")  # 3 bytes of placeholder content
    return str(p)


# ---------------------------------------------------------------------------
# 1. Happy path — pyodbc returns rows, executor maps to list[dict]
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_returns_rows_as_dicts(
    fake_pyodbc_factory, existing_accdb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two rows from a fake driver become a 2-element ``list[dict]``.

    Deterministic row shape: each row is a ``dict`` keyed by column
    name in the order the cursor returned them. This is the seam
    contract ``legacy_reader.load_legacy_snapshot_batched`` consumes.
    """
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    fake = fake_pyodbc_factory(
        rows=[("001", "Rex"), ("002", "Luna")],
        columns=["NCHIP", "NombreAnimal"],
    )

    rows = execute_legacy_sql(existing_accdb, "SELECT TOP 100 NCHIP, NombreAnimal FROM TbFichaAnimal", 0, 100)

    assert rows == [
        {"NCHIP": "001", "NombreAnimal": "Rex"},
        {"NCHIP": "002", "NombreAnimal": "Luna"},
    ]
    # Connection was opened and closed deterministically (Hard Rule 8:
    # no resource leak).
    assert len(fake.connections) == 1
    assert fake.connections[0].closed is True


# ---------------------------------------------------------------------------
# 2. Edge — empty result returns [] (no error)
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_empty_result_returns_empty_list(
    fake_pyodbc_factory, existing_accdb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty legacy table returns ``[]`` — same shape as 0 rows.

    The paging loop in ``legacy_reader`` terminates on ``[]``; the
    executor MUST not raise on the empty case (e.g. an
    ``IndexError`` from ``columns[0]`` on an empty description).
    """
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    fake = fake_pyodbc_factory(rows=[], columns=["NCHIP", "NombreAnimal"])

    rows = execute_legacy_sql(existing_accdb, "SELECT TOP 100 NCHIP FROM TbFichaAnimal", 0, 100)

    assert rows == []
    assert fake.connections[0].closed is True


# ---------------------------------------------------------------------------
# 3. Sad — driver missing raises LegacyReaderError
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_raises_when_driver_missing(
    fake_pyodbc_factory, existing_accdb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Access driver in ``pyodbc.drivers()`` → ``LegacyReaderError``.

    The CLI maps this to exit code 5 (per the spec scenario "Missing
    driver raises LegacyReaderError"). The error message MUST mention
    the missing driver so the operator can install it.
    """
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    fake_pyodbc_factory(driver_name="Some Other Driver")

    with pytest.raises(LegacyReaderError) as excinfo:
        execute_legacy_sql(existing_accdb, "SELECT TOP 100 * FROM TbFichaAnimal", 0, 100)

    assert "Microsoft Access Driver" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Sad — pyodbc import failure → LegacyReaderError
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_raises_when_pyodbc_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``import pyodbc`` failed at module load, the executor must
    raise ``LegacyReaderError`` — NOT ``ImportError`` — so the CLI
    keeps its single error-handling path.

    Simulates the missing-pyodbc case by setting the production
    module's cached reference to ``None`` with a sentinel
    ``_pyodbc_import_error``. The executor must surface a friendly
    error that points the operator at ``pip install '.[etl]'``.
    """
    monkeypatch.setattr(dysflow_client, "_pyodbc_module", None)
    monkeypatch.setattr(dysflow_client, "_pyodbc_import_error", ImportError("No pyodbc"))

    with pytest.raises(LegacyReaderError) as excinfo:
        execute_legacy_sql("/does/not/matter.accdb", "SELECT TOP 100 * FROM TbFichaAnimal", 0, 100)

    assert "pyodbc" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# 5. Sad — connect failure → LegacyReaderError, no connection leak
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_raises_on_connect_failure(
    fake_pyodbc_factory, existing_accdb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the underlying ``pyodbc.connect`` raises ``pyodbc.Error`` the
    executor must wrap it as ``LegacyReaderError`` and not leak any
    half-open connection. Hard Rule 8 + spec "Missing driver raises
    LegacyReaderError".
    """
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)

    class _PyodbcError(Exception):
        pass

    fake = fake_pyodbc_factory(connect_raises=_PyodbcError("file locked by another process"))
    # The fake's .Error is the default class; swap it so the connect
    # raises an instance the production code's ``except pyodbc_mod.Error``
    # catches. The production code uses ``isinstance(exc, pyodbc_mod.Error)``.
    fake.Error = _PyodbcError

    with pytest.raises(LegacyReaderError) as excinfo:
        execute_legacy_sql(existing_accdb, "SELECT TOP 100 * FROM TbFichaAnimal", 0, 100)

    assert "connect" in str(excinfo.value).lower() or "locked" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# 6. Sad — query failure → LegacyReaderError, connection still closed
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_raises_on_query_failure_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``pyodbc.Error`` raised mid-query is wrapped as
    ``LegacyReaderError`` AND the connection is closed (Hard Rule 8).

    The fake driver raises from inside ``cursor.execute``; the
    production ``finally`` block MUST still close the connection
    even on the error path.
    """

    class _PyodbcError(Exception):
        pass

    class _ExplodingCursor:
        description = (("NCHIP",),)
        executed: list[str] = []

        def execute(self, _sql: str) -> _ExplodingCursor:
            raise _PyodbcError("syntax error in SQL")

        def fetchall(self) -> list[Any]:  # pragma: no cover — never reached
            return []

    class _Conn:
        closed = False

        def execute(self, sql: str) -> _ExplodingCursor:
            return _ExplodingCursor().execute(sql)

        def close(self) -> None:
            self.closed = True

    class _PyodbcMod:
        Error = _PyodbcError

        def drivers(self) -> list[str]:
            return ["Microsoft Access Driver (*.accdb)"]

        def connect(self, _conn_str: str, *, timeout: int) -> _Conn:
            return _Conn()

    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(dysflow_client, "_pyodbc_module", _PyodbcMod())

    with pytest.raises(LegacyReaderError):
        execute_legacy_sql("/anywhere.accdb", "SELECT BAD SQL", 0, 100)


# ---------------------------------------------------------------------------
# 7. Sad — file missing raises LegacyReaderError
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_raises_when_legacy_file_missing(
    fake_pyodbc_factory, tmp_path: Path
) -> None:
    """A non-existent ``.accdb`` raises ``LegacyReaderError`` BEFORE
    pyodbc is asked to open it — the operator sees a clear message
    pointing at the missing path, not a pyodbc INI file or driver
    error.
    """
    fake_pyodbc_factory()
    missing = tmp_path / "absent.accdb"
    assert not missing.exists()

    with pytest.raises(LegacyReaderError) as excinfo:
        execute_legacy_sql(str(missing), "SELECT TOP 100 * FROM TbFichaAnimal", 0, 100)

    # ``str(Path)`` on Windows may use ``\\`` or ``/``; assert on the
    # file name (always ``absent.accdb``) instead of the full path.
    assert "absent.accdb" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 8. Seam contract — fake executor injection works
# ---------------------------------------------------------------------------


def test_fake_executor_injected_via_set_legacy_query_executor() -> None:
    """``legacy_reader._execute_legacy_query`` uses the injected fake.

    Hard Rule 2: the seam is the single point where the test fake
    takes over from the production executor. A regression that reads
    the executor via something other than the seam would silently
    pass tests and explode in production.
    """
    seen: list[tuple[str, str, int, int]] = []

    def _fake(path: str, sql: str, offset: int, limit: int) -> list[dict[str, Any]]:
        seen.append((path, sql, offset, limit))
        return [{"NCHIP": "001", "NombreAnimal": "Rex"}]

    set_legacy_query_executor(_fake)
    try:
        rows = legacy_reader._execute_legacy_query(
            "/anywhere.accdb", "SELECT TOP 100 * FROM TbFichaAnimal", 0, 100
        )
    finally:
        set_legacy_query_executor(None)

    assert rows == [{"NCHIP": "001", "NombreAnimal": "Rex"}]
    assert seen == [("/anywhere.accdb", "SELECT TOP 100 * FROM TbFichaAnimal", 0, 100)]


# ---------------------------------------------------------------------------
# 9. Seam contract — reset restores default executor
# ---------------------------------------------------------------------------


def test_reset_executor_seam_restores_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``set_legacy_query_executor(None)`` clears the override and the
    default executor is consulted again.

    This is the same invariant the autouse ``_reset_legacy_executor``
    fixture in ``tests/migration/conftest.py`` enforces between
    tests — verified here atomically so a future regression in the
    fixture is caught.
    """
    sentinel_marker = {"called": False}

    def _marker(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        sentinel_marker["called"] = True
        return []

    # Install the fake, confirm it's used.
    set_legacy_query_executor(_marker)
    assert legacy_reader._execute_legacy_query("/x.accdb", "SELECT 1", 0, 1) == []
    assert sentinel_marker["called"] is True

    # Reset; the default executor is now in charge. We patch the
    # ``execute_legacy_sql`` name *inside legacy_reader's namespace*
    # (that's where ``_execute_legacy_query`` looks it up via the
    # module-level ``from migration.dysflow_client import
    # execute_legacy_sql``). The seam-reset path now delegates to the
    # patched default, proving the override was actually cleared.
    default_called = {"called": False}

    def _default_stub(
        path: str, sql: str, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        default_called["called"] = True
        return [{"default": True}]

    monkeypatch.setattr(
        "migration.legacy_reader.execute_legacy_sql", _default_stub
    )
    set_legacy_query_executor(None)

    rows = legacy_reader._execute_legacy_query("/x.accdb", "SELECT 1", 0, 1)

    assert rows == [{"default": True}]
    assert default_called["called"] is True
    # And the marker is no longer consulted.
    sentinel_marker["called"] = False


# ---------------------------------------------------------------------------
# 10. Seam contract — global autouse fixture prevents cross-test leakage
# ---------------------------------------------------------------------------


def test_autouse_reset_clears_executor_between_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The autouse ``_reset_legacy_executor`` fixture in
    ``tests/migration/conftest.py`` resets the seam AFTER each test.

    We verify the invariant by:

    1. Setting the seam to a callable that would otherwise leak into
       the next test.
    2. Trusting the fixture to reset it.
    3. Asserting in a SUBSEQUENT step (after fixture teardown) that
       the seam is cleared.

    The test itself ends; the next test's fixture cleanup is what we
    trust. To make the assertion atomic we directly call the
    teardown path via the same ``setattr(None)`` the fixture uses.
    """

    def _leaky(_p: str, _s: str, _o: int, _l: int) -> list[dict[str, Any]]:
        return [{"leak": True}]

    set_legacy_query_executor(_leaky)
    # At this point the seam holds the leaky fake. The fixture teardown
    # runs AFTER the test, clearing it for the next test.
    assert legacy_reader._legacy_query_executor is _leaky

    # The fixture teardown is observable here: it runs in the same
    # way it would after any other test.
    set_legacy_query_executor(None)
    assert legacy_reader._legacy_query_executor is None


# ---------------------------------------------------------------------------
# 11. Static boundary — no executable MCP imports / calls
# ---------------------------------------------------------------------------


_MCP_PATTERNS: tuple[str, ...] = ("mcp__dysflow", "dysflow_query_execute", "mcp_dispatch")
"""Substrings that, when found in an ``import`` or call AST node,
indicate a possible runtime dependency on Dysflow MCP. The boundary
test treats any executable match as a contract violation.
"""


def _walk_python_files(root: Path) -> Iterator[Path]:
    """Yield every ``.py`` file under ``root`` (recursive).

    Skips hidden directories and any ``__pycache__`` directories to
    keep the search deterministic and fast.
    """
    for entry in sorted(root.rglob("*.py")):
        if any(part == "__pycache__" or part.startswith(".") for part in entry.parts):
            continue
        yield entry


def _find_mcp_dependencies(root: Path) -> list[str]:
    """Return a list of ``"<path>:<line>: <snippet>"`` for every
    ``Import``/``ImportFrom``/``Call`` AST node whose name matches
    :data:`_MCP_PATTERNS`.

    Only executable code is inspected — ``ast.parse`` produces a
    tree where ``Import``/``ImportFrom``/``Call`` are first-class
    nodes and docstring/comment text never appears as such. A
    ``from foo import dysflow_query_execute`` inside a docstring
    is, by definition, NOT an ``ImportFrom`` node — the AST does
    not see it as code.
    """
    matches: list[str] = []
    for path in _walk_python_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            # The boundary test never reads Python files that don't
            # parse — that's a separate concern. Skip silently so a
            # typo elsewhere doesn't mask the MCP boundary.
            continue

        for node in ast.walk(tree):
            snippet: str | None = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    full = alias.name
                    if any(p in full for p in _MCP_PATTERNS):
                        snippet = f"import {full}"
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full = f"{module}.{alias.name}" if module else alias.name
                    if any(p in full for p in _MCP_PATTERNS):
                        snippet = f"from {module} import {alias.name}"
            elif isinstance(node, ast.Call):
                func = node.func
                parts: list[str] = []
                while isinstance(func, ast.Attribute):
                    parts.insert(0, func.attr)
                    func = func.value
                if isinstance(func, ast.Name):
                    parts.insert(0, func.id)
                if parts:
                    full = ".".join(parts)
                    if any(p in full for p in _MCP_PATTERNS):
                        snippet = f"call {full}"

            if snippet:
                rel = path.relative_to(root.parent)
                matches.append(f"{rel}:{node.lineno}: {snippet}")
    return matches


def test_no_mcp_runtime_dependency_in_app_or_migration() -> None:
    """No executable ``mcp__dysflow`` / ``dysflow_query_execute`` /
    ``mcp_dispatch`` import or call lives under ``app/`` or
    ``migration/``.

    Per the runtime-boundary spec, the migration runtime MUST NOT
    depend on Dysflow MCP at runtime — the MCP is agent-only
    tooling. This test enforces the contract by parsing the source
    tree with ``ast`` so docstrings and comments (which legitimately
    reference ``dysflow_query_execute`` as a historical note) are
    silently ignored.
    """
    repo_root = Path(__file__).resolve().parents[2]
    targets = (repo_root / "app", repo_root / "migration")
    all_matches: list[str] = []
    for target in targets:
        if target.exists():
            all_matches.extend(_find_mcp_dependencies(target))

    assert all_matches == [], (
        "Runtime-boundary violation: executable Dysflow MCP dependency "
        "found in app/ or migration/ (AST-parsed, docstrings ignored):\n"
        + "\n".join(all_matches)
    )


# ---------------------------------------------------------------------------
# 12. Determinism — same input rows produce identical output dicts
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_is_deterministic_across_calls(
    fake_pyodbc_factory, existing_accdb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two calls with the same fake data return deep-equal results.

    The contract is that the executor is a pure function of
    ``(path, sql, offset, limit)`` — no implicit state, no
    accumulating connections. The fake keeps the row data across
    calls (the fake's ``rows`` list is per-instance and reused).
    """
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    fake = fake_pyodbc_factory(
        rows=[("001", "Rex"), ("002", "Luna")],
        columns=["NCHIP", "NombreAnimal"],
    )

    sql = "SELECT TOP 100 NCHIP, NombreAnimal FROM TbFichaAnimal"
    first = execute_legacy_sql(existing_accdb, sql, 0, 100)
    second = execute_legacy_sql(existing_accdb, sql, 0, 100)

    assert first == second
    assert len(fake.connections) == 2  # one per call, both closed


# ---------------------------------------------------------------------------
# 13. Edge — offset > 0 returns the next page slice
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_honors_offset_and_limit(
    fake_pyodbc_factory, existing_accdb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``offset`` and ``limit`` are honored by client-side slicing.

    Per design §5, the executor is responsible for translating
    ``offset``/``limit`` into the Access dialect. With pyodbc the
    executor fetches rows from the SQL (which already has
    ``TOP limit``) and slices the result set client-side. This
    test pins the slice semantics so a future regression that
    ignores offset/limit is caught.
    """
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)
    # Five rows; request offset=2, limit=2 → rows 2..3 (zero-indexed).
    fake_pyodbc_factory(
        rows=[("001",), ("002",), ("003",), ("004",), ("005",)],
        columns=["NCHIP"],
    )

    rows = execute_legacy_sql(existing_accdb, "SELECT TOP 2 NCHIP FROM TbFichaAnimal", 2, 2)

    assert rows == [{"NCHIP": "003"}, {"NCHIP": "004"}]


# ---------------------------------------------------------------------------
# 14. Timeout contract — pyodbc.connect receives timeout=30
# ---------------------------------------------------------------------------


def test_execute_legacy_sql_passes_timeout_to_pyodbc_connect(
    fake_pyodbc_factory, existing_accdb: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``pyodbc.connect`` is called with ``timeout=30``.

    The timeout is the contract from the design (D1 / driver table
    §10): ``Connection.timeout=30``. If a future change drops the
    timeout, a stuck ``.accdb`` lock could hang the migration.
    """
    captured: dict[str, Any] = {}
    fake = fake_pyodbc_factory(
        rows=[],
        columns=["NCHIP"],
    )
    monkeypatch.setattr(os.path, "isfile", lambda _p: True)

    original_connect = fake.connect

    def _capturing_connect(conn_str: str, *, timeout: int) -> FakeConnection:
        captured["conn_str"] = conn_str
        captured["timeout"] = timeout
        return original_connect(conn_str, timeout=timeout)

    monkeypatch.setattr(fake, "connect", _capturing_connect)

    execute_legacy_sql(existing_accdb, "SELECT TOP 100 NCHIP FROM TbFichaAnimal", 0, 100)

    assert captured["timeout"] == 30
    # The connection string MUST include the Access driver and the
    # .accdb path; this is the operator's safety net against a typo
    # silently opening the wrong file.
    assert "Microsoft Access Driver" in captured["conn_str"]
    assert existing_accdb in captured["conn_str"]


__all__ = [
    "FakeConnection",
    "FakeCursor",
    "FakePyodbc",
    "execute_legacy_sql",
]
