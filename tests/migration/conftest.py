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
- **Rule 7 — single harness form**: exactly one fake (``FakeLocalBackend``).
  Tests reuse it; no ``MockClient`` / ``StubClient`` / ``SpyClient``
  variants.
- **Rule 8 — no production mutation**: ``FakeLocalBackend`` holds rows
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

from app.core.data_access import BackendError
from migration import legacy_reader
from migration import lock as _migration_lock
from migration.apply import (
    _SAFE_TABLE_NAME,
    BOOTSTRAP_SHADOW_TABLE_SQL,
    apply_legacy_to_web,
)


class FakeLocalBackend:
    """In-memory ``LocalPostgresExecutor`` replacement.

    Routes a handful of SQL shapes:

    - ``CREATE TABLE IF NOT EXISTS web_only_feature_shadow`` — bootstrap,
      returns ``[]``.
    - ``INSERT INTO web_only_feature_shadow ...`` — appends the params
      payload (no column parsing) so tests can assert what was logged.
    - ``INSERT INTO <table> (...) RETURNING <cols>`` — extracts the
      column list, builds a row dict from params, returns a copy with
      a synthetic ``id``.
    - ``SELECT ... FROM <table>`` — returns the current rows; honors
      a simple ``WHERE col = $1`` by filtering on ``col``.
    - ``SELECT COUNT(*) FROM <table>`` — returns ``{"count": N}``.

    Unknown shapes return ``[]`` so a test that does not pre-load the
    table sees an empty result (Hard Rule 4: no humo, but a stub is
    not a "no exception" pass — the test asserts the post-state of
    ``tables[table]`` explicitly).

    The instance is fresh per test via the ``web_client`` fixture; no
    cross-test contamination.
    """

    def __init__(self) -> None:
        # Mirrors the real LocalBackend envelope shape so ``rows[0]`` calls
        # in production code path (e.g. when ``RETURNING`` returns rows)
        # work without modification.
        self.queries: list[tuple[str, list[Any] | None]] = []
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.buckets: dict[str, dict[str, Any]] = {}

    # --- public helpers used by tests --------------------------------
    def seed(self, table: str, rows: list[dict[str, Any]]) -> None:
        """Pre-load ``table`` with ``rows`` (Hard Rule 1)."""
        self.tables[table] = [dict(r) for r in rows]

    def all_rows(self, table: str) -> list[dict[str, Any]]:
        """Return a copy of every row currently in ``table``."""
        return [dict(r) for r in self.tables.get(table, [])]

    def get_bucket(self, bucket_name: str) -> dict[str, Any] | None:
        """Return a copy of bucket metadata, or ``None`` on miss."""
        bucket = self.buckets.get(bucket_name)
        return dict(bucket) if bucket is not None else None

    def ensure_bucket(self, bucket_name: str, *, is_public: bool = False) -> dict[str, Any]:
        """Create a missing bucket as private; fail closed on public state."""
        if is_public:
            raise ValueError("FakeLocalBackend only supports private buckets")
        existing = self.buckets.get(bucket_name)
        if existing is not None:
            if existing.get("isPublic") is not False:
                raise BackendError(
                    409,
                    {
                        "error": "bucket_public_violation",
                        "message": f"Bucket {bucket_name!r} exists but is public",
                    },
                )
            return dict(existing)
        bucket = {"bucketName": bucket_name, "isPublic": False}
        self.buckets[bucket_name] = bucket
        return dict(bucket)

    # --- duck-typed LocalPostgresExecutor surface ----------------------------
    def execute_sql(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.queries.append((query, params))
        q = query.strip()
        upper = q.upper()

        # --- bootstrap -------------------------------------------------
        if upper.startswith("CREATE TABLE"):
            # CREATE TABLE IF NOT EXISTS — no-op on second run.
            return []

        # --- shadow-state writes --------------------------------------
        if upper.startswith("INSERT INTO WEB_ONLY_FEATURE_SHADOW"):
            shadow = self.tables.setdefault("WEB_ONLY_FEATURE_SHADOW", [])
            payload = {
                "table_name": (params or [None])[0],
                "legacy_pk": (params or [None, None])[1] if params else None,
                "web_pk": (params or [None, None, None])[2] if params else None,
                "web_column": (params or [None, None, None, None])[3] if params else None,
                "preserved_value": (params or [None, None, None, None, None])[4]
                if params
                else None,
                "strategy": (params or [None, None, None, None, None, None])[5]
                if params
                else None,
                "reconciliation_status": (params or [None, None, None, None, None, None, None, None])[7]
                if params and len(params) > 7
                else None,
                "params": list(params or []),
                "query": query,
            }
            if "ON CONFLICT" in upper:
                for idx, row in enumerate(shadow):
                    if (
                        row.get("table_name") == payload["table_name"]
                        and row.get("legacy_pk") == payload["legacy_pk"]
                        and row.get("web_column") == payload["web_column"]
                    ):
                        shadow[idx] = payload
                        break
                else:
                    shadow.append(payload)
            else:
                shadow.append(payload)
            return []

        # --- shadow-state reads ---------------------------------------
        if upper.startswith("SELECT COUNT(*)"):
            # SELECT COUNT(*) FROM <table>
            tail = q.upper().split("FROM", 1)[1].strip().rstrip(";")
            table = tail.split()[0].strip('"').lower()
            return [{"count": len(self.tables.get(table, []))}]

        if upper.startswith("SELECT "):
            return self._route_select(q, params)

        # --- INSERT INTO <table> (domain tables) ---------------------
        if upper.startswith("INSERT INTO "):
            return self._route_insert(q, params)

        # --- UPDATE <table> SET ... -----------------------------------
        if upper.startswith("UPDATE "):
            # We don't mutate state on UPDATE in this slice; the apply
            # path emits a record-only ``UPDATE`` in the no-op case via
            # the shadow log (a real ``UPDATE`` would still execute on
            # the live DB; this fake records the call for assertions).
            # PR6 reverse applier relies on ``update_reconciliation_status``
            # which UPDATEs the shadow table — the fake routes those
            # UPDATEs to the matching shadow row so test atoms can
            # assert ``review_reasons`` / ``status`` propagation.
            if "WEB_ONLY_FEATURE_SHADOW" in upper:
                self._apply_shadow_update(q, params)
                return []
            return []

        # Defensive: a query we don't recognise returns empty. Tests
        # that NEED a non-empty result for an unknown shape must seed
        # the table explicitly — the fake never invents data.
        return []

    # --- internals --------------------------------------------------

    def _apply_shadow_update(
        self, query: str, params: list[Any] | None
    ) -> None:
        """Apply an UPDATE against ``web_only_feature_shadow`` to the in-memory store.

        PR6 reverse applier relies on ``update_reconciliation_status``
        (``migration.shadow_state.ShadowStateRepository``) to stamp
        the categorical review reasons on the reverse drift rows.
        The production SQL is parameterised in column order:
        ``SET reconciliation_status = %s, review_reasons = %s,
        last_reconciled_at = %s WHERE table_name = %s AND
        legacy_pk = %s AND web_column = %s``. The fake parses
        the WHERE clause and applies the SET clause to the
        matching in-memory shadow row.
        """
        shadow = self.tables.setdefault("WEB_ONLY_FEATURE_SHADOW", [])
        if not params:
            return
        # The production SQL parameter order (see migration/shadow_state.py):
        # params[0]=status, params[1]=review_reasons (JSON string),
        # params[2]=last_reconciled_at (ISO or None),
        # params[3]=table_name, params[4]=legacy_pk, params[5]=web_column.
        try:
            normalized = list(params) + [None] * (6 - len(params))
            status = normalized[0]
            review_reasons_json = normalized[1]
            last_reconciled_at = normalized[2]
            table_name = normalized[3]
            legacy_pk = normalized[4]
            web_column = normalized[5]
        except (IndexError, TypeError):
            return
        for row in shadow:
            if (
                row.get("table_name") == table_name
                and row.get("legacy_pk") == str(legacy_pk)
                and row.get("web_column") == web_column
            ):
                row["reconciliation_status"] = status
                row["review_reasons"] = review_reasons_json
                row["last_reconciled_at"] = last_reconciled_at
                break

    def _route_select(
        self, query: str, params: list[Any] | None
    ) -> list[dict[str, Any]]:
        # Naive parser: ``SELECT ... FROM <table>[ WHERE <col> = $1]``
        upper = query.upper()
        table = upper.split("FROM", 1)[1].strip().split()[0].rstrip(";").strip('"')
        table = table.lower()
        rows = list(self.tables.get(table, []))

        if "WHERE" not in upper:
            return rows

        # Extract ``col = $N`` from WHERE; match against params[N-1].
        where_clause = upper.split("WHERE", 1)[1]
        eq_token = where_clause.split()[0]  # best-effort first token
        col = eq_token.strip('"').lower()
        if params:
            value = params[0]
            return [r for r in rows if str(r.get(col)) == str(value)]
        return rows

    def _route_insert(
        self, query: str, params: list[Any] | None
    ) -> list[dict[str, Any]]:
        # ``INSERT INTO <table> (col1, col2, ...) VALUES ($1, $2, ...) RETURNING ...``
        upper = query.upper()
        # Parse table name (handle quoted identifier).
        after_insert = upper.split("INSERT INTO", 1)[1].strip()
        head = after_insert.split("(", 1)[0].strip()
        table = head.strip('"').lower()

        # Parse column list between first ( and matching ).
        cols_section = after_insert.split("(", 1)[1].split(")", 1)[0]
        cols = [c.strip().strip('"').lower() for c in cols_section.split(",")]

        row: dict[str, Any] = {}
        for col, value in zip(cols, params or [], strict=False):
            row[col] = value
        # Synthetic web_pk so callers can record the mapping. The real
        # DB does this server-side (DEFAULT gen_random_uuid()).
        row.setdefault("id", f"web-{len(self.tables.get(table, [])) + 1}")
        self.tables.setdefault(table, []).append(row)
        return [row]


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
def web_client() -> FakeLocalBackend:
    """Fresh in-memory LocalPostgresExecutor per test (Hard Rule 1)."""
    return FakeLocalBackend()


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
        client: FakeLocalBackend | None = None,
        table_name: str = "animal",
        legacy_path: str | None = None,
        lock_path: Path | None = None,
        since: Any = None,
        batch_size: int = 100,
    ) -> Any:
        client = client or FakeLocalBackend()
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
    "FakeLocalBackend",
    "_SAFE_TABLE_NAME",
    "apply_runner",
    "legacy_dummy_path",
    "web_client",
]
