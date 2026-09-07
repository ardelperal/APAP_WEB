"""Shared fixtures for ``tests/migration/`` (issue #168).

Hard Rules honoured (web-tdd-philosophy):

- **Rule 1 — fixture gate**: every test sets up its own rows via the
  ``web_client`` fixture's ``seed(...)`` and ``set_legacy(...)`` helpers.
  No pre-existing rows; no environment-dependent state.
- **Rule 2 — dependency injection**: ``apply_legacy_to_web`` receives
  the fake ``web_client`` as its first argument. The Dysflow legacy
  executor is injected via ``migration.legacy_reader.set_legacy_query_executor``
  in the ``set_legacy`` fixture (the same seam PR-3 of
  ``web-only-feature-preservation`` left open).
- **Rule 7 — single harness form**: exactly one fake (``FakeInsForge``).
  Tests reuse it; no ``MockClient`` / ``StubClient`` / ``SpyClient``
  variants.
- **Rule 8 — no production mutation**: ``FakeInsForge`` holds rows
  in memory only. The Dysflow mock returns canned rows from a dict,
  never touches a real ``.accdb``.

Why this fixture is hermetic:

- ``tmp_path`` is pytest-builtin (per-test temp directory).
- ``monkeypatch.setenv("APAP_MIGRATION_DIR", ...)`` keeps the
  ``migration_dir`` resolution deterministic per test.
- ``migration.legacy_reader.set_legacy_query_executor(None)`` runs in
  teardown so a Dysflow override from one test cannot leak into the
  next.

References:
    - ``web-tdd-philosophy`` skill, Hard Rules 1, 2, 7, 8.
    - ``migration.lock`` for the advisory-lock contract.
    - ``migration.legacy_reader`` for the Dysflow executor seam.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from migration import legacy_reader
from migration import lock as _migration_lock
from migration.apply import (
    _SAFE_TABLE_NAME,
    BOOTSTRAP_SHADOW_TABLE_SQL,
    apply_legacy_to_web,
)


class FakeInsForge:
    """In-memory test fake for the migration package web_client interface.

    Replaces the InsForge-backed fake that lived here before issue #669.
    The InsForge client module was deleted in #664; the migration
    package itself is being rewritten in #8. Until then, this stub
    captures calls for assertions and returns empty rows on every
    ``execute_sql`` so the apply_runner fixture can still drive the
    code paths the migration tests exercise.

    The instance is fresh per test via the ``web_client`` fixture; no
    cross-test contamination.
    """

    def __init__(self) -> None:
        self.queries: list[tuple[str, list[object] | None]] = []
        self.tables: dict[str, list[dict[str, object]]] = {}
        self.buckets: dict[str, dict[str, object]] = {}

    def seed(self, table: str, rows: list[dict[str, object]]) -> None:
        self.tables[table] = [dict(r) for r in rows]

    def all_rows(self, table: str) -> list[dict[str, object]]:
        return [dict(r) for r in self.tables.get(table, [])]

    def get_bucket(self, bucket_name: str) -> dict[str, object] | None:
        bucket = self.buckets.get(bucket_name)
        return dict(bucket) if bucket is not None else None

    def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, object]:
        raise NotImplementedError(
            "FakeInsForge.ensure_bucket: pending #8 migration package rewrite"
        )

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.queries.append((query, list(params) if params is not None else None))
        return []


# --- pytest fixtures ------------------------------------------------------


@pytest.fixture
def legacy_dummy_path(tmp_path: Path) -> str:
    """A non-existent ``.accdb`` path.

    The Dysflow mock returns canned rows without ever touching the path
    (Hard Rule 8). The string is still meaningful because the test
    asserts the applier passes it through to the executor.
    """
    return str(tmp_path / "legacy.accdb")


@pytest.fixture
def web_client() -> FakeInsForge:
    """Fresh in-memory LocalPostgresExecutor per test (Hard Rule 1)."""
    return FakeInsForge()


@pytest.fixture
def apply_runner() -> Any:
    """Callable wrapper around :func:`apply_legacy_to_web`.

    Returns a function that:

    - injects the per-call Dysflow executor (``set_legacy_query_executor``);
    - resolves the lock path to the test's ``tmp_path``;
    - defaults ``table_name="animal"`` so each test only specifies
      overrides it cares about.

    Use ``runner(legacy_rows=[...], seed={"animales": [...]}, **kwargs)``
    to drive the apply path.
    """

    captured: dict[str, Any] = {}

    def _run(
        *,
        legacy_rows: list[dict[str, Any]] | None = None,
        seed: dict[str, list[dict[str, Any]]] | None = None,
        dry_run: bool = False,
        client: FakeInsForge | None = None,
        table_name: str = "animal",
        legacy_path: str | None = None,
        lock_path: Path | None = None,
        since: Any = None,
        batch_size: int = 100,
    ) -> Any:
        client = client or FakeInsForge()
        if seed:
            for table, rows in seed.items():
                client.seed(table, rows)

        # Inject the Dysflow executor — returns ``legacy_rows`` for the
        # first batch (BATCH_SIZE = 100 by default) and ``[]`` after, so
        # the paging loop terminates.
        rows = list(legacy_rows or [])

        def _executor(
            _path: str, _sql: str, _offset: int, limit: int
        ) -> list[dict[str, Any]]:
            captured["path"] = _path
            captured["offset"] = _offset
            captured["limit"] = limit
            if _offset > 0:
                return []
            return rows[:limit]

        legacy_reader.set_legacy_query_executor(_executor)
        try:
            result = apply_legacy_to_web(
                client,
                table_name,
                legacy_path=legacy_path or "/dummy/legacy.accdb",
                since=since,
                batch_size=batch_size,
                dry_run=dry_run,
                lock_path=lock_path,
            )
        finally:
            legacy_reader.set_legacy_query_executor(None)

        captured["result"] = result
        captured["client"] = client
        return captured

    return _run


@pytest.fixture(autouse=True)
def _reset_legacy_executor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """Ensure no Dysflow executor leaks across tests.

    A previous test that forgot to clean up would otherwise poison the
    next one's legacy reads. Belt-and-braces — ``apply_runner`` already
    resets in its own ``finally``, but a test that bypasses the runner
    (e.g. a direct ``apply_legacy_to_web`` call) still benefits.
    """
    monkeypatch.setenv("APAP_MIGRATION_DIR", str(tmp_path))
    legacy_reader.set_legacy_query_executor(None)
    yield
    legacy_reader.set_legacy_query_executor(None)


@pytest.fixture(autouse=True)
def _default_msaccess_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Default the MSACCESS pre-flight to "no live Access window".

    PR3 introduced a fail-closed contract on
    ``migration.lock.check_msaccess_running`` — when ``psutil`` is
    missing or ``process_iter`` raises mid-iteration, the call raises
    ``MsAccessPreflightUnavailableError`` instead of silently claiming
    "no MSACCESS live". That change is correct for production, but the
    CI runner does not install ``psutil`` (it's only an operator-side
    prerequisite, documented in ``docs/runbooks/live-migration-apply.md``
    and enforced by ``migration.lock`` itself). Without this autouse,
    every pre-PR3 atom under ``tests/migration/`` that calls
    ``apply_legacy_to_web`` would now raise the pre-flight-unavailable
    exception in CI regardless of the atom's intent.

    Tests that want to exercise the pre-flight failure or the
    pre-flight success path override this autouse with their own
    ``monkeypatch.setattr("migration.apply.check_msaccess_running", ...)``
    inside the test body; the later ``setattr`` wins against
    ``monkeypatch``'s stack (which restores in reverse order on
    teardown). The PR3 ``TestMsaccessPreflightFailClosed`` and
    ``TestMsaccessPreflight`` classes in ``test_apply_safety.py`` use
    exactly that pattern via the ``_patch_apply_seams`` helper, so the
    fail-closed contract continues to be pinned by the explicit
    override.
    """
    monkeypatch.setattr(
        "migration.apply.check_msaccess_running",
        lambda: [],
    )

    class _FakePsutil:
        """No-process stand-in for the optional ``psutil`` dependency.

        CI environments do not install ``psutil`` (operator-side only per
        ``docs/runbooks/live-migration-apply.md`` and enforced by
        ``migration.lock`` itself). The pre-PR6 happy-path tests did
        not exercise ``check_msaccess_running`` because they imported
        ``apply_legacy_to_web`` from ``migration.apply`` directly; PR6
        added ``apply_web_to_legacy`` via ``migration.reverse_apply``
        which calls ``check_msaccess_running`` unconditionally, so the
        seam must satisfy CI even without ``psutil`` on the PATH.
        ``migration.lock.check_msaccess_running`` does
        ``getattr(sys.modules['migration.lock'], 'psutil', None)`` and
        raises ``MsAccessPreflightUnavailableError`` if the result is
        ``None``. Setting ``_PSUTIL_AVAILABLE = True`` alone is not
        enough; we also need a non-``None`` ``psutil`` attribute.
        """

        @staticmethod
        def process_iter(*_args: Any, **_kwargs: Any) -> Iterator[Any]:
            return iter(())

        @staticmethod
        def pid_exists(_pid: int) -> bool:
            return False

    # Bind a non-``None`` ``psutil`` on the lock module so the
    # ``or psutil_obj is None`` short-circuit does not fire on CI; the
    # function returns an empty list because the closure-set
    # ``migration.apply.check_msaccess_running`` (above) wins the
    # lookup when ``apply_legacy_to_web`` / ``apply_web_to_legacy``
    # calls it via the ``migration.apply`` module. The
    # ``TestMsaccessPreflightFailClosed`` class flips
    # ``_PSUTIL_AVAILABLE`` back to ``False`` (and overrides
    # ``check_msaccess_running``) to exercise the failure shape —
    # see that class for the override.
    monkeypatch.setattr(_migration_lock, "psutil", _FakePsutil)
    monkeypatch.setattr(_migration_lock, "_PSUTIL_AVAILABLE", True)
    yield


__all__ = [
    "BOOTSTRAP_SHADOW_TABLE_SQL",
    "FakeInsForge",
    "_SAFE_TABLE_NAME",
    "apply_runner",
    "legacy_dummy_path",
    "web_client",
]
