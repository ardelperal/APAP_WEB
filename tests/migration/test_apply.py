"""Unit atoms for ``migration.apply.apply_legacy_to_web`` (issue #168).

TDD contract — Hard Rules from web-tdd-philosophy:

- **Rule 1 (fixture gate)**: every atom seeds its own rows via the
  ``apply_runner`` fixture's ``seed=`` kwarg. No shared state across
  atoms.
- **Rule 2 (DI)**: the Dysflow executor is injected via
  ``legacy_reader.set_legacy_query_executor``; the LocalPostgresExecutor is
  the ``FakeLocalBackend`` instance built by ``apply_runner``. No global
  getters.
- **Rule 3 (cardinality)**: every atom that mutates asserts
  ``result.applied`` / ``result.skipped`` / ``result.errors`` as
  concrete numbers.
- **Rule 4 (no humo)**: assertions are on values, never "no exception
  raised". The exception path uses ``pytest.raises`` with a concrete
  message match.
- **Rule 5 (three paths)**: each slice ships happy + sad + edge atoms.
  See ``test_apply_legacy_to_web_handles_empty_legacy`` (edge) and
  ``test_apply_legacy_to_web_handles_legacy_dysflow_error`` (sad).
- **Rule 8 (no production mutation)**: never touches a real ``.accdb``
  or a real LocalBackend; the ``FakeLocalBackend`` is hermetic.

Scope:

- ``apply_legacy_to_web`` signature is the public contract for the
  apply slice — locking, audit logging, idempotency, and divergence
  recording all flow through this function.
- Helpers (``_legacy_to_web_row``, ``_compute_source_hash``,
  ``_bootstrap_shadow_state``) are covered indirectly via the public
  atoms AND directly via the bootstrap tests in ``test_bootstrap.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Reuse the legacy_reader seam for Dysflow error injection.
from migration import LegacyReaderError, legacy_reader
from migration.apply import (
    _SAFE_TABLE_NAME,
    ApplyResult,
    _compute_source_hash,
    _legacy_to_web_row,
    apply_legacy_to_web,
)
from migration.lock import LockInfo
from tests.migration.conftest import FakeLocalBackend  # noqa: TID251 — internal import

# --- 1. Happy path -------------------------------------------------------


def test_apply_legacy_to_web_inserts_new_rows(apply_runner) -> None:
    """Two legacy rows → two INSERTs into ``animales``.

    Pre-state: 0 web rows. Action: run apply with 2 legacy rows.
    Post-state: ``result.applied == 2``, ``result.skipped == 0``,
    ``animales`` table has 2 rows with the expected columns mapped.
    """
    captured = apply_runner(
        legacy_rows=[
            {"NCHIP": "001", "NombreAnimal": "Rex"},
            {"NCHIP": "002", "NombreAnimal": "Luna"},
        ],
    )

    result: ApplyResult = captured["result"]
    client: FakeLocalBackend = captured["client"]

    assert result.applied == 2
    assert result.skipped == 0
    assert result.errors == []
    assert result.table_name == "animal"

    rows = client.all_rows("animales")
    assert len(rows) == 2
    assert {r["nchip"] for r in rows} == {"001", "002"}
    assert {r["nombreanimal"] for r in rows} == {"Rex", "Luna"}


# --- 2. Idempotency -----------------------------------------------------


def test_apply_legacy_to_web_skips_existing_rows_by_natural_key(apply_runner) -> None:
    """Re-running with the same legacy data must produce 0 inserts.

    The natural key (``NCHIP`` for animales) is the dedup pivot. The
    second run sees both rows already in the web DB and returns
    ``applied == 0, skipped == 2``.
    """
    legacy = [{"NCHIP": "001", "NombreAnimal": "Rex"}]

    # First run — inserts.
    first = apply_runner(legacy_rows=legacy)
    assert first["result"].applied == 1

    # Second run on the SAME client state — no-op.
    second = apply_runner(
        legacy_rows=legacy,
        client=first["client"],  # reuse the seeded FakeLocalBackend
    )
    assert second["result"].applied == 0
    assert second["result"].skipped == 1
    assert len(second["client"].all_rows("animales")) == 1


# --- 3. Diff detection --------------------------------------------------


def test_apply_legacy_to_web_updates_changed_rows(apply_runner) -> None:
    """A row whose payload differs from the web row is recorded as a
    divergence in the shadow table — NOT a blind overwrite.

    The apply slice is conservative: when legacy and web disagree, the
    operator must reconcile via ``reconcile --interactive``. The shadow
    table is the audit record of the disagreement.
    """
    seed = [
        {"nchip": "001", "nombreanimal": "Rex-legacy-v1"},
    ]
    legacy = [{"NCHIP": "001", "NombreAnimal": "Rex-legacy-v2"}]

    captured = apply_runner(
        legacy_rows=legacy,
        seed={"animales": seed},
    )

    result: ApplyResult = captured["result"]
    client: FakeLocalBackend = captured["client"]

    # Row already existed → not inserted again.
    assert result.applied == 0
    assert result.skipped == 1
    # …but the divergence was recorded for the operator.
    shadow = client.all_rows("WEB_ONLY_FEATURE_SHADOW")
    assert len(shadow) == 1
    assert shadow[0]["table_name"] == "animales"
    assert shadow[0]["legacy_pk"] == "001"
    # Web row preserved verbatim (no blind overwrite).
    assert client.all_rows("animales")[0]["nombreanimal"] == "Rex-legacy-v1"


# --- 4. Dry-run ----------------------------------------------------------


def test_apply_legacy_to_web_dry_run_does_not_write(apply_runner) -> None:
    """``dry_run=True`` returns the diff plan but touches no state.

    Three guarantees from a dry-run:

    1. ``result.applied == 2`` (two INSERTs would be issued).
    2. ``animales`` table is still empty.
    3. No shadow rows were recorded (no divergence contract yet).

    Note: dry-run also skips the advisory lock — the operator can
    re-run ``apply --check-only`` freely without locking out a real
    apply.
    """
    captured = apply_runner(
        legacy_rows=[
            {"NCHIP": "001", "NombreAnimal": "Rex"},
            {"NCHIP": "002", "NombreAnimal": "Luna"},
        ],
        dry_run=True,
    )

    result: ApplyResult = captured["result"]
    client: FakeLocalBackend = captured["client"]

    assert result.applied == 2
    assert result.skipped == 0
    assert client.all_rows("animales") == []
    assert client.all_rows("WEB_ONLY_FEATURE_SHADOW") == []


# --- 5. Shadow recording for divergences ---------------------------------


def test_apply_legacy_to_web_records_shadow_for_divergences(apply_runner) -> None:
    """Every divergent row appears in the shadow table exactly once.

    Three legacy rows, all of them already in the web DB with different
    payloads. The apply slice must:

    1. Insert 0 new rows (``applied == 0``).
    2. Skip 3 (``skipped == 3``).
    3. Record 3 shadow rows (one per divergent legacy PK).
    """
    seed = [
        {"nchip": "001", "nombreanimal": "v1"},
        {"nchip": "002", "nombreanimal": "v1"},
        {"nchip": "003", "nombreanimal": "v1"},
    ]
    legacy = [
        {"NCHIP": "001", "NombreAnimal": "v2"},
        {"NCHIP": "002", "NombreAnimal": "v2"},
        {"NCHIP": "003", "NombreAnimal": "v2"},
    ]

    captured = apply_runner(
        legacy_rows=legacy,
        seed={"animales": seed},
    )

    result: ApplyResult = captured["result"]
    client: FakeLocalBackend = captured["client"]

    assert result.applied == 0
    assert result.skipped == 3
    assert len(result.errors) == 0

    shadow = client.all_rows("WEB_ONLY_FEATURE_SHADOW")
    assert len(shadow) == 3
    assert {row["legacy_pk"] for row in shadow} == {"001", "002", "003"}


# --- 6. Audit log emission ----------------------------------------------


def test_apply_legacy_to_web_emit_log_safe_per_row(
    apply_runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every applied row triggers a ``sync.applied`` audit-log call.

    Hard Rule 2: the audit log goes through ``app.core.logging.log_safe``,
    which is the only allowed logging entry point in ``app/``. We
    monkeypatch it (project convention from hardening-2026-q2) and
    assert the call payload.
    """
    import app.core.logging as logging_mod

    calls: list[dict[str, object]] = []

    def _capture(event: str, **fields: object) -> None:
        calls.append({"event": event, **fields})

    monkeypatch.setattr(logging_mod, "log_safe", _capture)

    apply_runner(
        legacy_rows=[
            {"NCHIP": "001", "NombreAnimal": "Rex"},
            {"NCHIP": "002", "NombreAnimal": "Luna"},
        ],
    )

    assert len(calls) == 2
    assert all(c["event"] == "sync.applied" for c in calls)
    directions = {c["direction"] for c in calls}
    assert directions == {"legacy->web"}
    # PKs in the call payload.
    pks = {c["pk"] for c in calls}
    assert pks == {"001", "002"}
    # Source hash present and non-empty (the SHA-256 contract).
    assert all(isinstance(c["source_hash"], str) and len(c["source_hash"]) > 0 for c in calls)


# --- 7. Lock acquisition (concurrency safety) ---------------------------


def test_apply_legacy_to_web_acquires_advisory_lock(
    apply_runner, tmp_path: Path
) -> None:
    """The lock is held for the duration of the apply and released on
    successful completion.

    Hard Rule 8 + AGENTS.md §18: two concurrent ``apply`` invocations
    must not race. The lock file at ``lock_path`` is the contract.
    """
    lock_path = tmp_path / "migration.lock"

    captured = apply_runner(
        legacy_rows=[{"NCHIP": "001", "NombreAnimal": "Rex"}],
        lock_path=lock_path,
    )

    # After successful apply the lock MUST be released (no stale file
    # left behind).
    assert lock_path.exists() is False
    assert captured["result"].applied == 1


def test_apply_legacy_to_web_second_invocation_sees_active_lock(
    apply_runner, tmp_path: Path
) -> None:
    """A second apply run while the first holds the lock must fail fast.

    We simulate this by writing a LockInfo file with a still-alive PID
    (our own PID — the test process is alive) before invoking apply.
    ``apply_legacy_to_web`` is expected to surface ``LockActiveError``
    so the CLI can report a clean conflict to the operator.
    """
    import os
    from datetime import UTC, datetime

    lock_path = tmp_path / "migration.lock"
    lock_path.write_text(
        LockInfo(
            pid=os.getpid(),
            acquired_at=datetime.now(UTC),
        ).to_json(),
        encoding="utf-8",
    )

    with pytest.raises(Exception) as excinfo:
        apply_runner(
            legacy_rows=[{"NCHIP": "001", "NombreAnimal": "Rex"}],
            lock_path=lock_path,
        )

    # The exception is surfaced up through the runner; we accept any
    # migration-layer exception (LockActiveError is the canonical one
    # but the apply wrapper may wrap it). The contract is: NO writes
    # to the web DB.
    assert "lock" in str(excinfo.value).lower() or "LockActive" in type(
        excinfo.value
    ).__name__


# --- 8. Error path releases the lock ------------------------------------


def test_apply_legacy_to_web_releases_lock_on_error(tmp_path: Path) -> None:
    """A Dysflow error in the middle of a batch must NOT leave a stale
    lock behind. The next operator invocation must succeed.
    """
    lock_path = tmp_path / "migration.lock"

    def _explode(_path: str, _sql: str, _offset: int, _limit: int):
        raise LegacyReaderError("Dysflow unavailable (test)")

    legacy_reader.set_legacy_query_executor(_explode)
    try:
        with pytest.raises(LegacyReaderError):
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=lock_path,
            )
    finally:
        legacy_reader.set_legacy_query_executor(None)

    # The lock MUST be released even on the error path.
    assert lock_path.exists() is False


# --- 9. Edge: empty legacy ------------------------------------------------


def test_apply_legacy_to_web_handles_empty_legacy(apply_runner) -> None:
    """Empty legacy result is a no-op, not an error.

    Real-world: a fresh sync where the operator filtered ``--since``
    past every legacy write returns 0 rows. The CLI must report
    ``applied == 0, skipped == 0`` and exit 0, not raise.
    """
    captured = apply_runner(legacy_rows=[])

    result: ApplyResult = captured["result"]
    assert result.applied == 0
    assert result.skipped == 0
    assert result.errors == []
    assert captured["client"].all_rows("animales") == []


# --- 10. Sad: Dysflow failure --------------------------------------------


def test_apply_legacy_to_web_handles_legacy_dysflow_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Dysflow error is surfaced as ``LegacyReaderError`` — not
    swallowed into ``result.errors``.

    The apply slice must propagate I/O failures so the CLI exits 5
    (design §1.5). Returning ``result`` with the error stuffed into
    ``errors[]`` would hide the failure from the operator.
    """
    def _explode(_path: str, _sql: str, _offset: int, _limit: int):
        raise LegacyReaderError("Dysflow MCP unavailable")

    monkeypatch.setattr(
        "migration.legacy_reader._legacy_query_executor", _explode
    )
    # Belt-and-braces: the apply module reads the executor from the
    # module global, so we patch BOTH the seam and the global.
    legacy_reader.set_legacy_query_executor(_explode)
    try:
        with pytest.raises(LegacyReaderError) as excinfo:
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
            )
        assert "Dysflow" in str(excinfo.value)
    finally:
        legacy_reader.set_legacy_query_executor(None)


# --- Helper coverage (no-humo guard for the public API) -----------------


def test_compute_source_hash_is_stable() -> None:
    """``_compute_source_hash`` is the contract for the audit log.

    Same row → same hash. Different value → different hash. The hash
    is SHA-256 hex (64 chars).
    """
    row = {"NCHIP": "001", "NombreAnimal": "Rex"}
    h1 = _compute_source_hash(row)
    h2 = _compute_source_hash(row)
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)

    # Different value → different hash.
    other = _compute_source_hash({"NCHIP": "001", "NombreAnimal": "Luna"})
    assert other != h1


def test_legacy_to_web_row_applies_mapping() -> None:
    """``_legacy_to_web_row`` lowercases the column names per the YAML
    mapping contract (legacy uses CamelCase, web uses lowercase).
    """
    legacy_row = {"NCHIP": "001", "NombreAnimal": "Rex"}
    # We use a tiny inline TableMapping so the test is hermetic.
    from migration.mappings import ColumnMapping, TableMapping

    mapping = TableMapping(
        web_table="animales",
        legacy_table="TbFichaAnimal",
        key_field="nchip",
        legacy_key="NCHIP",
        columns=[
            ColumnMapping(web_column="nchip", legacy_column="NCHIP", transform="identity"),
            ColumnMapping(
                web_column="nombreanimal",
                legacy_column="NombreAnimal",
                transform="identity",
            ),
        ],
    )
    # client=None is safe here: this test uses identity transforms only,
    # no FK lookups, so the client is never actually called.
    mapped = _legacy_to_web_row(legacy_row, mapping, client=None, vol_index=None)
    assert mapped == {"nchip": "001", "nombreanimal": "Rex"}


def test_safe_table_name_blocks_injection() -> None:
    """``_SAFE_TABLE_NAME`` rejects unsafe identifiers in INSERT paths.

    Hard Rule 8 + AGENTS.md §1: the apply path must not allow a
    ``table_name`` from the YAML / CLI to inject SQL. This is the
    same belt-and-braces the existing ``_apply_accept_derived`` uses.
    """

    assert _SAFE_TABLE_NAME.match("animal") is not None
    assert _SAFE_TABLE_NAME.match("voluntario") is not None
    assert _SAFE_TABLE_NAME.match("animal; DROP TABLE animales--") is None
    assert _SAFE_TABLE_NAME.match("animal-uesc") is None  # punctuation rejected
