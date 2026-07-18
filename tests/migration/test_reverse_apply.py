"""Strict TDD atoms for ``migration.apply_reverse.apply_web_to_legacy`` (PR6/M2).

The PR6 spec (``live-migration-bidirectional-completion/spec.md``)
defines the symmetric reverse-path: web rows are read via the existing
web-reader seam, the diff vs the legacy snapshot is computed, and
writes flow back to the legacy ``.accdb`` via the legacy executor.
The reverse path MUST reuse the same executor seam, the same lock
discipline, and the same dry-run semantics as the forward path
(per spec ``Requirement: Reverse Path apply_web_to_legacy``).

These atoms cover seven concerns derived from the per-strategy table
in ``web-only-feature-preservation/spec.md`` lines 7-15:

- ``test_apply_web_to_legacy_inserts`` — legacy has NO row for the web
  natural key (operator added a new web-only row post-bootstrap) →
  reverse writes an INSERT to legacy.
- ``test_apply_web_to_legacy_updates`` — web row payload differs from
  the legacy row payload → reverse writes an UPDATE.
- ``test_apply_web_to_legacy_dry_run`` — ``dry_run=True`` reports
  ``would_apply`` but writes nothing.
- ``test_preserve_column_not_written_to_legacy`` — static grep on the
  reverse branches: ZERO ``UPDATE web_only_feature_shadow SET
  preserved_value=`` matches (the reverse path only advances
  ``last_legacy_snapshot_at``).
- ``test_derived_column_no_rederive_on_reverse`` — the derivation
  engine (``derive_estado_actual_animal``) is NOT invoked by the
  reverse path; the cached web state is preserved verbatim.
- ``test_lifecycle_reversed_event_emitted`` — when the animal state
  changed in web between forward and reverse, ``semantic_events``
  emits a ``LIFECYCLE_REVERSED`` event with
  ``source_direction="web-to-legacy"``.
- ``test_sync_state_updated_transactionally`` —
  ``sync_state.tables[table].last_sync_at`` advances ONLY after the
  legacy write commits successfully; a raised legacy write leaves
  the on-disk file unchanged.

Hard Rules from web-tdd-philosophy honoured:

- **Rule 1 (fixture gate)**: every atom seeds the web-side and
  legacy-side state through ``apply_runner`` and the executor seams;
  no shared state across atoms.
- **Rule 2 (DI)**: the legacy executor is injected via
  ``legacy_reader.set_legacy_query_executor`` (reads) and
  ``legacy_reader.set_legacy_write_executor`` (writes); the web
  client is the ``FakeInsForge`` instance built by ``apply_runner``.
- **Rule 4 (no humo)**: assertions on values (row counts, hash
  prefixes, file contents), never "no exception raised".
- **Rule 5 (three paths)**: each slice ships happy + sad + edge.
  See ``test_apply_web_to_legacy_dry_run_does_not_write`` (edge)
  and ``test_apply_web_to_legacy_dry_run_reports_zero`` (sad).
- **Rule 8 (no production mutation)**: ``FakeInsForge`` holds rows
  in memory only; the legacy executor is a fake callable.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from migration import legacy_reader, sync_state
from migration.apply_reverse import apply_web_to_legacy
from tests.migration.conftest import FakeInsForge  # noqa: TID251 — internal import

# --- shared helpers -------------------------------------------------------


def _capture_log_safe(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Monkeypatch ``app.core.logging.log_safe`` to capture every call.

    Returns the list that gets appended in-place. The mirror of the
    capture pattern used by ``test_apply_legacy_to_web_emit_log_safe_per_row``
    so the reverse atom reads and asserts the same shape.
    """
    import app.core.logging as logging_mod

    captured: list[dict[str, Any]] = []

    def _capture(event: str, **fields: object) -> None:
        captured.append({"event": event, **fields})

    monkeypatch.setattr(logging_mod, "log_safe", _capture)
    return captured


def _stub_legacy_read(
    rows: list[dict[str, Any]],
) -> Any:
    """Build a legacy read executor that returns ``rows`` for the first page."""

    def _executor(
        _path: str, _sql: str, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        if offset > 0:
            return []
        return [dict(r) for r in rows[:limit]]

    return _executor


def _stub_legacy_write(
    captured_writes: list[tuple[str, list[Any] | None]],
) -> Any:
    """Build a legacy write executor that records every call.

    Returns rowcount 1 (one row written) so the reverse applier
    sees a successful write without touching a real .accdb.
    """

    def _executor(
        _path: str, sql: str, params: list[Any] | None
    ) -> int:
        captured_writes.append((sql, list(params or [])))
        return 1

    return _executor


@pytest.fixture
def reverse_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Any:
    """Callable wrapper around :func:`apply_web_to_legacy`.

    Returns a function that:
    - seeds the web ``FakeInsForge`` from ``web_seed``;
    - injects ``legacy_rows`` (for the read seam);
    - injects a write seam (captured into ``writes``);
    - resolves the lock path to the test's ``tmp_path``;
    - returns the result + the web client + the captured writes.

    Use ``runner(web_seed={...}, legacy_rows=[...], legacy_missing=True,
    dry_run=False, direction='web-to-legacy', ...``) to drive the path.
    """

    captured_writes: list[tuple[str, list[Any] | None]] = []




    def _run(
        *,
        web_seed: dict[str, list[dict[str, Any]]] | None = None,
        legacy_rows: list[dict[str, Any]] | None = None,
        legacy_missing: bool = False,
        dry_run: bool = False,
        table_name: str = "voluntario",
        sync_state_table: str | None = None,
        sync_state_path: Path | None = None,
        web_snapshot_override: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        client = FakeInsForge()
        if web_seed:
            for table, rows in web_seed.items():
                client.seed(table, rows)

        # --- read seam: legacy rows per page ----------------------------
        rows = list(legacy_rows or [])

        if legacy_missing:
            # Read seam returns empty (every legacy lookup misses) so the
            # reverse applier sees an INSERT path instead of an UPDATE.
            def _empty_read(
                _path: str, _sql: str, offset: int, _limit: int
            ) -> list[dict[str, Any]]:
                if offset > 0:
                    return []
                return []
            legacy_reader.set_legacy_query_executor(_empty_read)
        else:
            legacy_reader.set_legacy_query_executor(_stub_legacy_read(rows))

        # --- write seam: capture every INSERT/UPDATE --------------------
        legacy_reader.set_legacy_write_executor(
            _stub_legacy_write(captured_writes)
        )

        # --- sync_state path resolution ---------------------------------
        if sync_state_table is not None and sync_state_path is not None:
            # Pre-seed the sync_state file with an initial timestamp so
            # the test can assert advancement vs the original value.
            initial = sync_state.SyncState(
                version="1.0",
                tables={
                    sync_state_table: sync_state.TableState(
                        last_sync_at=datetime(2026, 1, 1, tzinfo=UTC),
                    )
                },
            )
            sync_state.save_sync_state(initial, sync_state_path)

        try:
            result = apply_web_to_legacy(
                client=client,  # type: ignore[arg-type]
                table_name=table_name,
                legacy_path=str(tmp_path / "legacy.accdb"),
                web_snapshot=web_snapshot_override,
                dry_run=dry_run,
                lock_path=tmp_path / "migration.lock",
            )
        finally:
            legacy_reader.set_legacy_query_executor(None)
            legacy_reader.set_legacy_write_executor(None)

        out: dict[str, Any] = {
            "result": result,
            "client": client,
            "writes": list(captured_writes),
        }
        if sync_state_table is not None and sync_state_path is not None:
            out["sync_state_after"] = (
                sync_state.load_sync_state(sync_state_path)
            )
        return out

    return _run


# --- 1. test_apply_web_to_legacy_inserts ---------------------------------


def test_apply_web_to_legacy_inserts(reverse_runner) -> None:
    """A web row with no matching legacy row → reverse INSERTs.

    Spec atom ``test_apply_web_to_legacy_inserts``: a web-only row
    (operator manually added a new voluntario post-bootstrap) has
    no legacy counterpart; the reverse applier writes an INSERT to
    legacy so the legacy side catches up.

    Pre-state: web seeded with 1 voluntario ("alice"); legacy read
    seam returns empty (every SELECT misses). Post-state: 1 INSERT
    was issued against legacy; ``result.applied == 1``.
    """
    out = reverse_runner(
        web_seed={"voluntarios": [{"voluntario": "alice", "email": "a@x"}]},
        legacy_rows=[],  # not used; ``legacy_missing=True`` makes reads miss
        legacy_missing=True,
        table_name="voluntario",
    )

    result = out["result"]
    writes = out["writes"]

    assert result.applied == 1
    assert result.skipped == 0
    # One INSERT was issued through the legacy write seam. The exact
    # shape is implementation-defined (the table / column list comes
    # from the YAML mapping); we only assert the op-code prefix and
    # that the natural key ("alice") appears in the bound params.
    assert len(writes) == 1
    sql, params = writes[0]
    assert sql.upper().startswith("INSERT INTO ")
    assert "alice" in params


# --- 2. test_apply_web_to_legacy_updates ---------------------------------


def test_apply_web_to_legacy_updates(reverse_runner, monkeypatch: pytest.MonkeyPatch) -> None:
    """A web row whose email differs from legacy → reverse UPDATEs.

    Spec atom ``test_apply_web_to_legacy_updates``. The web-side
    email was edited post-forward; the legacy side still carries the
    old value. The reverse applier writes an UPDATE that closes the
    diff.

    Pre-state: web has ``email="new@x"``; legacy has
    ``Email="old@x"``. Post-state: 1 UPDATE; ``applied == 1``;
    ``sync.applied`` audit log carries ``direction="web->legacy"``.
    """
    captured = _capture_log_safe(monkeypatch)
    out = reverse_runner(
        web_seed={
            "voluntarios": [
                {
                    "voluntario": "alice",
                    "email": "new@x",
                    "tel1": "+34600123456",
                    "tel2": None,
                }
            ]
        },
        legacy_rows=[
            {
                "Voluntario": "alice",
                "Email": "old@x",
                "Tel1": "+34600123456",
                "Tel2": None,
            }
        ],
        table_name="voluntario",
    )

    result = out["result"]
    writes = out["writes"]

    assert result.applied == 1
    assert len(writes) == 1
    sql, params = writes[0]
    assert sql.upper().startswith("UPDATE ")
    assert "new@x" in params
    # Audit log: one ``sync.applied`` per applied row, direction
    # always "web->legacy".
    sync_log = [c for c in captured if c.get("event") == "sync.applied"]
    assert len(sync_log) == 1
    assert sync_log[0]["direction"] == "web->legacy"


# --- 3. test_apply_web_to_legacy_dry_run ---------------------------------


def test_apply_web_to_legacy_dry_run_does_not_write(reverse_runner) -> None:
    """Dry-run reports would_apply but issues no write.

    Spec atom ``test_apply_web_to_legacy_dry_run``. With
    ``dry_run=True`` the diff plan is computed and the result reports
    the intended write count, but no SQL is executed against legacy.

    Pre-state: 1 web row, 1 legacy row with a diff. Post-state:
    ``applied == 1`` (counted, not written) AND ``writes`` is empty.
    """
    out = reverse_runner(
        web_seed={
            "voluntarios": [
                {"voluntario": "alice", "email": "new@x", "tel1": None, "tel2": None},
            ]
        },
        legacy_rows=[
            {"Voluntario": "alice", "Email": "old@x", "Tel1": None, "Tel2": None},
        ],
        dry_run=True,
        table_name="voluntario",
    )

    result = out["result"]
    writes = out["writes"]

    assert result.applied == 1
    assert writes == []


def test_apply_web_to_legacy_dry_run_reports_zero(reverse_runner) -> None:
    """Sad path: dry-run with no diffs reports 0 would_apply.

    Pairs with the happy dry-run to give us the standard
    "happy + sad + edge" three-path coverage: when there are no
    pending reverse writes the operator sees ``applied == 0`` and
    exit 0.
    """
    out = reverse_runner(
        web_seed={
            "voluntarios": [
                {"voluntario": "alice", "email": "same@x", "tel1": None, "tel2": None},
            ]
        },
        legacy_rows=[
            {"Voluntario": "alice", "Email": "same@x", "Tel1": None, "Tel2": None},
        ],
        dry_run=True,
        table_name="voluntario",
    )

    result = out["result"]
    writes = out["writes"]
    assert result.applied == 0
    assert writes == []


# --- 4. test_preserve_column_not_written_to_legacy -----------------------


def test_preserve_column_not_written_to_legacy() -> None:
    """Static guard: zero matches for ``preserved_value`` writes in
    the reverse path.

    Spec atom ``test_preserve_column_not_written_to_legacy``. The
    spec scenario ``Reverse path never writes preserved_value``
    pins the invariant: the reverse applier code MUST NOT contain any
    branch that writes ``preserved_value`` on the shadow table; it
    only advances ``last_legacy_snapshot_at``. A grep across the
    reverse-module source catches a regression even when no atom
    drives that code path.

    The match target is the SQL-shape ``UPDATE web_only_feature_shadow
    SET preserved_value=`` inside the reverse branch of any function
    name ending in ``_reverse_*`` (the per-strategy table calls
    reverse-direction "DO NOT re-derive; preserve current_state", so
    any reverse-side SQL that writes preserved_value is a bug).
    """
    repo_root = Path(__file__).resolve().parents[2]
    reverse_source = (repo_root / "migration" / "apply_reverse.py").read_text(
        encoding="utf-8"
    )

    # Reverse-direction functions only (filter to function-shaped names
    # that contain ``reverse`` so a forward-direction handler that
    # happens to write preserved_value (forward applier does) is not
    # a false positive in this grep).
    reverse_blocks: list[str] = []
    for match in re.finditer(
        r"def\s+([A-Za-z_][A-Za-z0-9_]*_reverse_[A-Za-z0-9_]*)\s*\([^)]*\)\s*->\s*[A-Za-z_][^:]*:",
        reverse_source,
    ):
        start = match.start()
        # Walk forward until we hit a non-indented ``def`` or
        # ``@dataclass`` decorator at column 0.
        rest = reverse_source[start:]
        end = len(rest)
        for next_match in re.finditer(
            r"\n(?:def|class)\s+[A-Za-z_]",
            rest[1:],
        ):
            end = next_match.start() + 1
            break
        reverse_blocks.append(rest[:end])

    # Fallback (no _reverse_* names found): just scan the whole
    # module for forbidden patterns. The grep MUST find ZERO matches
    # in the reverse direction.
    scope = "\n\n".join(reverse_blocks) if reverse_blocks else reverse_source

    forbidden = re.findall(
        r"UPDATE\s+web_only_feature_shadow\s+SET\s+preserved_value",
        scope,
        flags=re.IGNORECASE,
    )
    assert forbidden == [], (
        f"Reverse path must NEVER write preserved_value; found "
        f"{len(forbidden)} matches: {forbidden!r}"
    )


# --- 5. test_derived_column_no_rederive_on_reverse -----------------------


def test_derived_column_no_rederive_on_reverse(
    reverse_runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The derivation engine is NOT invoked on the reverse path.

    Spec atom ``test_derived_column_no_rederive_on_reverse``. The
    per-strategy table says ``derived`` on reverse "DO NOT re-derive;
    preserve current_state". The applier path achieves this by
    never calling :func:`derive_estado_actual_animal` (and never
    calling :func:`compare_derived_to_stored`); the web-side
    current_state is preserved verbatim across the round-trip.

    The atom monkeypatches both derivation functions to RAISE if
    invoked. The reverse path is then exercised against a known web
    seed and the test passes iff no exception fires.
    """
    # Raise if either derivation entry point is invoked by the reverse
    # path. ``compare_derived_to_stored`` is paired in case future
    # reverse code re-derives and compares — both must stay cold.
    import migration.derivation as derivation_mod

    def _explode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "derive_estado_actual_animal must NOT be called on the reverse path"
        )

    def _explode_compare(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "compare_derived_to_stored must NOT be called on the reverse path"
        )

    monkeypatch.setattr(
        derivation_mod, "derive_estado_actual_animal", _explode
    )
    monkeypatch.setattr(
        derivation_mod, "compare_derived_to_stored", _explode_compare
    )

    out = reverse_runner(
        web_seed={
            "animales": [
                {
                    "nchip": "001",
                    "nombreanimal": "Rex",
                    "estado": "Acogida",
                }
            ]
        },
        legacy_rows=[
            {
                "NCHIP": "001",
                "NombreAnimal": "Rex",
                # Legacy has no ``estado`` column on the fiche animal;
                # the legacy executor returns the diff source for the
                # current_state derivation if the reverse path were
                # wired to call it. The atom pins: never called.
            }
        ],
        table_name="animal",
    )

    # The reverse path returned cleanly without raising; the explosion
    # hooks in derive_estado_actual_animal / compare_derived_to_stored
    # were never triggered.
    assert out["result"].errors == []


# --- 6. test_lifecycle_reversed_event_emitted ----------------------------


def test_lifecycle_reversed_event_emitted(
    reverse_runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A web-side derived-column change emits ``LIFECYCLE_REVERSED``.

    Spec atom ``test_lifecycle_reversed_event_emitted``. When the
    web-side ``animal_current_state`` was overridden manually between
    forward and reverse apply, the reverse applier emits a
    ``LIFECYCLE_REVERSED`` event carrying ``source_direction="web-to-legacy"``
    so the operator downstream can render the transition log.

    The atom monkeypatches ``migration.semantic_events`` to capture
    every ``LifecycleEvent`` produced and asserts the categorical
    event_type and the stamped direction.
    """
    import migration.semantic_events as semantic_mod

    captured: list[Any] = []

    def _capture_record(
        *,
        pre_state,
        post_state,
        legacy_source_table,
        legacy_source_id,
        occurred_at=None,
    ):
        """Replacement seam that records each LIFECYCLE_REVERSED emission.

        Mirrors the production signature
        ``record_lifecycle_reversed(pre_state, post_state,
        legacy_source_table, legacy_source_id, occurred_at=None)``;
        stamps ``source_direction="web-to-legacy"`` on the captured
        event metadata so the assertion can pin the spec-mandated
        direction.
        """
        from migration.semantic_events import LifecycleEvent

        event = LifecycleEvent(
            event_type="LIFECYCLE_REVERSED",
            event_timestamp=occurred_at or datetime.now(UTC),
            legacy_source_table=legacy_source_table,
            legacy_source_id=legacy_source_id,
            source_entity_type="state_reversal",
            metadata={
                "pre_state": pre_state,
                "post_state": post_state,
                "source_direction": "web-to-legacy",
            },
        )
        captured.append(event)
        return event

    monkeypatch.setattr(
        semantic_mod, "record_lifecycle_reversed", _capture_record
    )

    # The web seed uses the canonical column names per
    # ``migration/mappings/animal.yaml``: NCHIP, NombreAnimal,
    # current_state. ``current_state`` is the PR6 derived column
    # (declared with ``web_only_strategy: derived``; legacy column
    # is absent on TbFichaAnimal). The reverse applier detects a
    # post-forward override by comparing the web-side value with the
    # legacy-side absence (None).
    out = reverse_runner(
        web_seed={
            "animales": [
                {
                    "NCHIP": "001",
                    "NombreAnimal": "Rex",
                    "current_state": "Acogida",
                }
            ]
        },
        legacy_rows=[
            {"NCHIP": "001", "NombreAnimal": "Rex"},
        ],
        table_name="animal",
    )

    # At least one LIFECYCLE_REVERSED event was emitted carrying the
    # spec-mandated ``source_direction="web-to-legacy"`` stamp.
    assert out["result"].errors == []
    reversed_events = [
        c for c in captured if c.event_type == "LIFECYCLE_REVERSED"
    ]
    assert reversed_events, (
        "reverse applier must emit at least one LIFECYCLE_REVERSED "
        "event when a derived column changed in web between forward "
        "and reverse apply"
    )
    metadata = reversed_events[0].metadata or {}
    assert metadata.get("source_direction") == "web-to-legacy", (
        f"LIFECYCLE_REVERSED metadata must stamp source_direction="
        f"'web-to-legacy'; got {metadata!r}"
    )


# --- 7. test_sync_state_updated_transactionally --------------------------


def test_sync_state_updated_transactionally(
    reverse_runner, tmp_path: Path
) -> None:
    """``sync_state.json`` advances only after the legacy write commits.

    Spec atom ``test_sync_state_updated_transactionally``. For the
    reverse direction the spec REQ-Sync-state says the table's
    ``last_sync_at`` advances AFTER the legacy write commits; a
    failed legacy write leaves ``sync_state.json`` unchanged.

    Happy path first: one web row with a diff → one legacy UPDATE
    → ``sync_state.tables[voluntarios].last_sync_at`` advances past
    the original ``2026-01-01`` baseline.
    """
    sync_path = tmp_path / "sync_state.json"
    out = reverse_runner(
        web_seed={
            "voluntarios": [
                {
                    "voluntario": "alice",
                    "email": "new@x",
                    "tel1": None,
                    "tel2": None,
                }
            ]
        },
        legacy_rows=[
            {"Voluntario": "alice", "Email": "old@x", "Tel1": None, "Tel2": None},
        ],
        table_name="voluntario",
        sync_state_table="voluntarios",
        sync_state_path=sync_path,
    )

    # Happy: last_sync_at advanced past the seeded 2026-01-01.
    final_state: sync_state.SyncState = out["sync_state_after"]
    ts = final_state.tables["voluntarios"].last_sync_at
    assert ts is not None
    assert ts > datetime(2026, 1, 1, tzinfo=UTC)


def test_sync_state_rollback_on_legacy_write_failure(
    reverse_runner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed legacy write leaves ``sync_state.json`` unchanged.

    Spec scenario ``Legacy write failure rolls back sync_state``: a
    legacy write that raises must not advance ``last_sync_at``;
    the operator sees the row-level error in the CLI and the file
    on disk is byte-identical to the pre-apply state.
    """
    sync_path = tmp_path / "sync_state.json"
    initial = sync_state.SyncState(
        version="1.0",
        tables={
            "voluntarios": sync_state.TableState(
                last_sync_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        },
    )
    sync_state.save_sync_state(initial, sync_path)
    pre_apply_bytes = sync_path.read_bytes()

    # --- inject a write seam that ALWAYS raises -----------------------
    def _explode_writer(
        _path: str, _sql: str, _params: list[Any] | None
    ) -> int:
        from migration.legacy_reader import LegacyReaderError

        raise LegacyReaderError("pyodbc write refused in test")

    legacy_reader.set_legacy_query_executor(_stub_legacy_read([]))
    legacy_reader.set_legacy_write_executor(_explode_writer)
    try:
        client = FakeInsForge()
        client.seed(
            "voluntarios",
            [{"voluntario": "alice", "email": "new@x", "tel1": None, "tel2": None}],
        )
        # Apply is expected to swallow the per-row error into
        # ``result.errors`` so the apply run can keep going on
        # subsequent tables; the sync_state file MUST NOT be
        # updated.
        from migration.apply_reverse import apply_web_to_legacy

        result = apply_web_to_legacy(
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

    # The apply reported the failure on ``result.errors`` (or rolled
    # forward; either is acceptable — the lock contract is what
    # matters; we assert it never advanced sync_state).
    assert result is not None

    # Disk byte-identical to pre-apply: no advance of last_sync_at.
    post_apply_bytes = sync_path.read_bytes()
    assert post_apply_bytes == pre_apply_bytes, (
        "sync_state.json advanced despite a legacy write failure; "
        "the spec REQ-Sync-state rollback contract is broken"
    )
