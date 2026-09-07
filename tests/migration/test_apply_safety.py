"""Tests for PR3/M1 apply-safety wiring (ordering, pre-flight, partial-apply).

These atoms live in ``tests/migration/test_apply.py`` per the task
spec (``tasks.md`` PR3 3.1). They cover:

- MSACCESS pre-flight: abort when live, proceed when clear, dry-run
  bypasses (per design §6 three-path matrix).
- Snapshot ordering: written AFTER lock, BEFORE first legacy read;
  skipped on dry-run; written even when source is empty.
- Drift detection: existing snapshot with a different ``.accdb`` hash
  fails the apply closed.
- Partial-apply evidence: written on SIGINT after the snapshot;
  NOT written on SIGINT before the snapshot. Entry guard fails closed
  when a partial-apply file exists from a previous interrupted run.

Hard Rules honoured:

- Rule 1 (fixture gate): every test uses ``tmp_path`` for the lock,
  snapshot, and partial-apply files; FakeLocalBackend is per-test.
- Rule 2 (DI): MSACCESS, snapshot, and partial-apply seams are
  monkeypatched per-test. The executor is injected via the existing
  ``set_legacy_query_executor`` seam.
- Rule 6 (refactor-safety): assertions are on outcomes (file existence,
  event order, raised exceptions), not on internal helper calls.
- Rule 8 (no production mutation): no real Access / LocalBackend / psutil
  invocations — the MSACCESS check returns a list the test controls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from migration import legacy_reader
from migration.apply import apply_legacy_to_web
from migration.lock_snapshot import (
    SCHEMA_VERSION,
    PhotosManifest,
    Snapshot,
)
from tests.migration.conftest import FakeLocalBackend

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _events_recorder() -> dict[str, list[str]]:
    """Shared events recorder for ordering assertions."""
    return {"events": []}


def _patch_apply_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: dict[str, list[str]],
    msaccess_pids: list[int] | None = None,
    snap_when_written: Snapshot | None = None,
    existing_partial: dict[str, Any] | None = None,
    existing_snapshot: Snapshot | None = None,
    executor_behavior: str = "empty",
) -> None:
    """Monkeypatch the seams ``apply_legacy_to_web`` consults in PR3.

    Each parametrised test controls the exact subset it cares about;
    defaults give a "clean run" that is friendly to the existing
    happy-path tests in this file.
    """
    events_list = events["events"]

    def fake_check_msaccess() -> list[int]:
        events_list.append("check_msaccess")
        return msaccess_pids if msaccess_pids is not None else []

    def fake_compute_accdb(_path: str) -> str:
        events_list.append("compute_accdb")
        return "a" * 64

    def fake_compute_photos(_path: str | None) -> PhotosManifest:
        events_list.append("compute_photos")
        return PhotosManifest(file_count=0, total_bytes=0, sha256="b" * 64)

    def fake_read_snapshot(_path: str) -> Snapshot | None:
        events_list.append("read_snapshot")
        return existing_snapshot

    def fake_write_snapshot(
        _path: str,
        *,
        direction: str,
        accdb_sha256: str,
        photos_manifest: PhotosManifest,
    ) -> Snapshot:
        events_list.append("write_snapshot")
        if snap_when_written is not None:
            return snap_when_written
        return Snapshot(
            schema_version=SCHEMA_VERSION,
            direction=direction,
            started_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            accdb_sha256=accdb_sha256,
            photos_dir_sha256=photos_manifest.sha256,
            photos_file_count=photos_manifest.file_count,
            photos_total_bytes=photos_manifest.total_bytes,
        )

    def fake_read_partial(_path: str) -> dict[str, Any] | None:
        events_list.append("read_partial")
        return existing_partial

    def fake_write_partial(
        _path: str,
        *,
        direction: str,
        table_name: str,
        progress_applied: int,
        progress_total: int | None,
        reason: str,
    ) -> None:
        events_list.append("write_partial")

    def fake_acquire_lock(_path: Path) -> None:
        events_list.append("acquire_lock")

    def fake_release_lock(_path: Path) -> None:
        events_list.append("release_lock")

    def fake_executor(_p: str, _sql: str, _offset: int, _limit: int) -> list[dict[str, Any]]:
        events_list.append("executor")
        if executor_behavior == "empty":
            return []
        if executor_behavior == "raise_keyboard_interrupt":
            raise KeyboardInterrupt()
        if executor_behavior == "raise_keyboard_interrupt_after_first_batch":
            # First call returns one row; subsequent calls (or any further
            # iteration) raise KeyboardInterrupt.
            counter = fake_executor.counter = getattr(fake_executor, "counter", 0) + 1
            if counter == 1:
                return [{"NCHIP": "chip-1", "NombreAnimal": "Test"}]
            raise KeyboardInterrupt()
        return []

    monkeypatch.setattr("migration.apply.check_msaccess_running", fake_check_msaccess)
    monkeypatch.setattr("migration.apply.compute_accdb_hash", fake_compute_accdb)
    monkeypatch.setattr(
        "migration.apply.compute_photos_dir_hash", fake_compute_photos
    )
    monkeypatch.setattr("migration.apply.read_snapshot", fake_read_snapshot)
    monkeypatch.setattr("migration.apply.write_snapshot", fake_write_snapshot)
    monkeypatch.setattr("migration.apply.read_partial_apply", fake_read_partial)
    monkeypatch.setattr("migration.apply.write_partial_apply", fake_write_partial)
    monkeypatch.setattr("migration.apply.acquire_lock", fake_acquire_lock)
    monkeypatch.setattr("migration.apply.release_lock", fake_release_lock)
    legacy_reader.set_legacy_query_executor(fake_executor)


# --------------------------------------------------------------------------
# MSACCESS pre-flight
# --------------------------------------------------------------------------


class TestMsaccessPreflight:
    """``check_msaccess_running()`` blocks real apply when MSACCESS is live."""

    def test_apply_with_msaccess_running_aborts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A live MSACCESS process blocks the apply before lock/read.

        Per design §6 matrix: ``MSACCESS open → exit 5 + runbook URL``.
        The CLI surfaces the ``MsAccessRunningError`` as exit code 5;
        the library raises it. Either way the lock is NOT acquired and
        the legacy executor is NOT called.
        """
        events = _events_recorder()
        _patch_apply_seams(monkeypatch, events=events, msaccess_pids=[12345])

        from migration.apply import MsAccessRunningError

        with pytest.raises(MsAccessRunningError) as excinfo:
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )
        assert excinfo.value.pids == [12345]
        # MSACCESS was checked …
        assert "check_msaccess" in events["events"]
        # … and the lock was never acquired or released.
        assert "acquire_lock" not in events["events"]
        assert "release_lock" not in events["events"]
        # … and the legacy executor was never invoked.
        assert "executor" not in events["events"]
        # Belt-and-braces: no lock file appeared on disk.
        assert (tmp_path / "migration.lock").exists() is False

    def test_apply_without_msaccess_proceeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """No MSACCESS live → preflight returns [] and apply runs to completion."""
        events = _events_recorder()
        _patch_apply_seams(monkeypatch, events=events, msaccess_pids=[])

        result = apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            lock_path=tmp_path / "migration.lock",
        )

        assert result.applied == 0
        assert result.errors == []
        assert "check_msaccess" in events["events"]
        assert "acquire_lock" in events["events"]
        assert "executor" in events["events"]

    def test_apply_dry_run_skips_msaccess_preflight(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``--check-only`` (dry_run=True) bypasses the MSACCESS pre-flight.

        The design §6 matrix specifies: ``MSACCESS pre-flight … --check-only skips``.
        Operators can run ``apply --check-only`` to review counts and
        hashes without opening / closing Access.
        """
        events = _events_recorder()
        # If MSACCESS check ran, this would abort. We expect it NOT to run.
        _patch_apply_seams(monkeypatch, events=events, msaccess_pids=[12345])

        result = apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            dry_run=True,
            lock_path=tmp_path / "migration.lock",
        )

        assert result.applied == 0
        assert result.errors == []
        assert "check_msaccess" not in events["events"]
        # Lock is also skipped in dry-run.
        assert "acquire_lock" not in events["events"]


# --------------------------------------------------------------------------
# Snapshot ordering
# --------------------------------------------------------------------------


class TestSnapshotOrdering:
    """The snapshot is written AFTER lock, BEFORE first read."""

    def test_snapshot_written_after_lock_before_first_read(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Lock → write_snapshot → first executor call, in that order.

        Per design D8: snapshot ordering is locked so SIGINT before
        snapshot leaves no trace; SIGINT after snapshot leaves a
        snapshot and a partial-apply file.
        """
        events = _events_recorder()
        _patch_apply_seams(monkeypatch, events=events, executor_behavior="empty")

        apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            lock_path=tmp_path / "migration.lock",
        )

        e = events["events"]
        assert e.index("acquire_lock") < e.index("write_snapshot")
        assert e.index("write_snapshot") < e.index("executor")

    def test_snapshot_absent_when_dry_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Dry-run / ``--check-only`` does NOT write the snapshot.

        The user's directive: dry-run / check-only must not mutate the
        snapshot or infrastructure (per spec REQ-Snap-1 read-only
        compare). The apply path is the only mutation surface.
        """
        events = _events_recorder()
        _patch_apply_seams(monkeypatch, events=events, executor_behavior="empty")

        apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            dry_run=True,
            lock_path=tmp_path / "migration.lock",
        )

        assert "write_snapshot" not in events["events"]
        assert "acquire_lock" not in events["events"]
        assert "executor" in events["events"]  # read still happens for counts

    def test_snapshot_writes_with_empty_legacy_source(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An empty legacy source (zero rows) still produces a snapshot.

        The snapshot is the source-identity record; it MUST exist even
        when there are no rows to apply so the operator can see the
        fingerprints of the files they pointed at.
        """
        events = _events_recorder()
        _patch_apply_seams(monkeypatch, events=events, executor_behavior="empty")

        result = apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/empty.accdb",
            lock_path=tmp_path / "migration.lock",
        )

        assert result.applied == 0
        assert result.errors == []
        assert "write_snapshot" in events["events"]


# --------------------------------------------------------------------------
# Drift detection
# --------------------------------------------------------------------------


class TestDriftDetection:
    """A pre-existing snapshot with different hashes fails the apply closed."""

    def test_apply_fails_closed_on_drift(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Existing snapshot with different hashes → apply refuses to run.

        Per design §8 and the proposal D-LIVE-07: drift between
        consecutive apply runs is an auditable signal; the operator
        must explicitly acknowledge the change (a follow-up PR will
        expose a ``--accept-drift`` flag). PR3 fails closed: any
        difference aborts the apply with ``SourceDriftError``.
        """
        from datetime import UTC, datetime

        existing = Snapshot(
            schema_version=SCHEMA_VERSION,
            direction="legacy-to-web",
            started_at=datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC),
            accdb_sha256="z" * 64,  # different from current "a"*64
            photos_dir_sha256="b" * 64,
            photos_file_count=0,
            photos_total_bytes=0,
        )
        events = _events_recorder()
        _patch_apply_seams(
            monkeypatch,
            events=events,
            existing_snapshot=existing,
            executor_behavior="empty",
        )

        from migration.apply import SourceDriftError

        with pytest.raises(SourceDriftError) as excinfo:
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )
        # The drift was about the .accdb hash (z*64 vs a*64).
        assert excinfo.value.accdb_sha256_changed is True
        # Lock released; no executor called (drift short-circuits before read).
        assert "release_lock" in events["events"]
        assert "executor" not in events["events"]

    def test_apply_proceeds_when_existing_snapshot_matches(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Existing snapshot with identical hashes → apply runs.

        Idempotent re-run case: same source, same apply. The drift
        detector should report ``drifted=False`` and the apply should
        proceed.
        """
        # Use ``hashlib`` to compute the same hashes that the patched
        # ``compute_accdb_hash`` and ``compute_photos_dir_hash`` return,
        # so the drift comparison sees identical values.
        from datetime import UTC, datetime

        accdb_hash = "a" * 64
        photos_hash = "b" * 64
        existing = Snapshot(
            schema_version=SCHEMA_VERSION,
            direction="legacy-to-web",
            started_at=datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC),
            accdb_sha256=accdb_hash,
            photos_dir_sha256=photos_hash,
            photos_file_count=0,
            photos_total_bytes=0,
        )

        events = _events_recorder()
        _patch_apply_seams(
            monkeypatch,
            events=events,
            existing_snapshot=existing,
            executor_behavior="empty",
        )

        result = apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            lock_path=tmp_path / "migration.lock",
        )

        assert result.applied == 0
        assert result.errors == []
        # The new snapshot was written (overwriting the existing one).
        assert "write_snapshot" in events["events"]
        # The executor ran.
        assert "executor" in events["events"]


# --------------------------------------------------------------------------
# Partial-apply evidence
# --------------------------------------------------------------------------


class TestPartialApplyEvidence:
    """``partial_apply.json`` lifecycle: written on SIGINT, gates future runs."""

    def test_apply_writes_partial_apply_on_sigint_after_snapshot(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """SIGINT after the snapshot persists snapshot + partial evidence.

        Per design D8: SIGINT AFTER snapshot → snapshot persists, lock
        released, ``partial_apply.json`` written. The next apply sees
        the partial evidence and fails closed (see
        ``test_apply_fails_closed_on_existing_partial_evidence``).
        """
        events = _events_recorder()
        _patch_apply_seams(
            monkeypatch,
            events=events,
            executor_behavior="raise_keyboard_interrupt_after_first_batch",
        )

        with pytest.raises(KeyboardInterrupt):
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )

        e = events["events"]
        assert "write_snapshot" in e
        assert "executor" in e
        assert "write_partial" in e
        # The partial evidence write happens AFTER the executor raised.
        assert e.index("write_partial") > e.index("executor")
        # Lock was released by the ``_LockContext.__exit__``.
        assert "release_lock" in e

    def test_apply_sigint_before_snapshot_does_not_write_partial(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """SIGINT before the snapshot leaves no snapshot and no partial file.

        Per design D8: SIGINT BEFORE snapshot → lock released, no
        snapshot, no partial evidence. The next apply starts clean.
        """
        events = _events_recorder()

        def fake_acquire_lock(_path: Path) -> None:
            events["events"].append("acquire_lock")
            raise KeyboardInterrupt()

        _patch_apply_seams(monkeypatch, events=events, executor_behavior="empty")
        monkeypatch.setattr("migration.apply.acquire_lock", fake_acquire_lock)

        with pytest.raises(KeyboardInterrupt):
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )

        e = events["events"]
        assert "acquire_lock" in e
        assert "write_snapshot" not in e
        assert "write_partial" not in e
        # Belt-and-braces: no partial file on disk.
        assert not (tmp_path / "migration.partial_apply.json").exists()

    def test_apply_fails_closed_on_existing_partial_evidence(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An existing ``partial_apply.json`` blocks the apply.

        Resume-safety contract: a previous run was interrupted; the
        operator MUST review the evidence and remove the file before
        retrying. PR3 does NOT auto-delete the file (no destructive
        cleanup, per user directive).
        """
        events = _events_recorder()
        _patch_apply_seams(
            monkeypatch,
            events=events,
            existing_partial={
                "schema_version": SCHEMA_VERSION,
                "direction": "legacy-to-web",
                "table_name": "animal",
                "progress_applied": 42,
                "progress_total": None,
                "reason": "sigint",
                "recorded_at": "2026-07-10T12:00:00+00:00",
            },
            executor_behavior="empty",
        )

        from migration.apply import PartialApplyInterruptedError

        with pytest.raises(PartialApplyInterruptedError) as excinfo:
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )
        assert "42" in str(excinfo.value) or "animal" in str(excinfo.value)
        # The lock was NOT acquired (fail fast at entry).
        assert "acquire_lock" not in events["events"]
        # The executor was NOT called.
        assert "executor" not in events["events"]

    def test_apply_dry_run_skips_partial_evidence_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Dry-run does NOT consult partial-apply evidence.

        ``--check-only`` is a read-only compare; the operator may
        run it freely to review counts/hashes without resolving any
        prior interruption.
        """
        events = _events_recorder()
        _patch_apply_seams(
            monkeypatch,
            events=events,
            existing_partial={"reason": "sigint"},  # would block if checked
            executor_behavior="empty",
        )

        result = apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            dry_run=True,
            lock_path=tmp_path / "migration.lock",
        )

        assert result.applied == 0
        assert "read_partial" not in events["events"]
        assert "acquire_lock" not in events["events"]


# --------------------------------------------------------------------------
# MSACCESS preflight fail-closed (PR3 verification remediation)
# --------------------------------------------------------------------------


class TestMsaccessPreflightFailClosed:
    """The MSACCESS preflight MUST NOT silently fail open.

    Per user directive 2026-07-11 (PR3 verification remediation):
    when ``psutil`` is missing or ``process_iter`` raises during a
    REAL apply, the apply must fail closed with a typed
    ``MsAccessPreflightUnavailableError`` (CLI exit 5, reason
    ``msaccess_preflight_unavailable``). A categorical ``log_safe``
    event is emitted with the reason — no PIDs, no error strings.
    Dry-run remains read-only and may skip the preflight.

    Hard Rules honoured:

    - Rule 1 (fixture gate): every test owns its FakeLocalBackend,
      tmp_path, and monkeypatched seams.
    - Rule 2 (DI): the preflight seam is monkeypatched; no real
      psutil import / process scan.
    - Rule 4 (no humo): assertions pin concrete exception types,
      exit codes, log event names, and log field values.
    - Rule 8 (no production mutation): no real Access / LocalBackend /
      psutil invocations.
    """

    def test_apply_fails_closed_when_psutil_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``psutil`` missing → ``MsAccessPreflightUnavailableError`` with reason ``psutil_missing``.

        A real apply must NEVER proceed when the preflight cannot run.
        The previous PR3 implementation returned ``[]`` (fail-open),
        which silently claimed "no MSACCESS live" while the check was
        unable to run. The remediation raises a typed exception
        mapped to CLI exit 5.
        """
        from migration import MsAccessPreflightUnavailableError

        def raise_unavailable() -> list[int]:
            raise MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            )

        monkeypatch.setattr(
            "migration.apply.check_msaccess_running", raise_unavailable
        )

        with pytest.raises(MsAccessPreflightUnavailableError) as excinfo:
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )
        assert excinfo.value.reason == (
            MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
        )

    def test_apply_fails_closed_when_process_iteration_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``process_iter`` raises → ``MsAccessPreflightUnavailableError`` with reason ``process_iteration_failed``.

        The previous PR3 implementation caught iteration errors and
        returned the partial PIDs (fail-open). The remediation
        raises a typed exception mapped to CLI exit 5.
        """
        from migration import MsAccessPreflightUnavailableError

        def raise_unavailable() -> list[int]:
            raise MsAccessPreflightUnavailableError(
                reason=(
                    MsAccessPreflightUnavailableError.REASON_PROCESS_ITERATION_FAILED
                )
            )

        monkeypatch.setattr(
            "migration.apply.check_msaccess_running", raise_unavailable
        )

        with pytest.raises(MsAccessPreflightUnavailableError) as excinfo:
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )
        assert excinfo.value.reason == (
            MsAccessPreflightUnavailableError.REASON_PROCESS_ITERATION_FAILED
        )

    def test_apply_logs_categorical_event_when_preflight_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A ``log_safe`` event is emitted with categorical reason — no PIDs, no error strings.

        The apply catches ``MsAccessPreflightUnavailableError``,
        emits ``log_safe("apply.preflight_unavailable", reason=...)``
        for audit, and re-raises. The log event MUST carry only the
        categorical reason — no PIDs, no psutil error messages, no
        path data (per AGENTS.md §18 privacy default-deny).
        """
        from migration import MsAccessPreflightUnavailableError

        captured: list[tuple[str, dict[str, Any]]] = []

        def fake_log_safe(event: str, **fields: Any) -> None:
            captured.append((event, fields))

        def raise_unavailable() -> list[int]:
            raise MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            )

        monkeypatch.setattr(
            "migration.apply.check_msaccess_running", raise_unavailable
        )
        monkeypatch.setattr("migration.apply.logging_mod.log_safe", fake_log_safe)

        from migration import MsAccessPreflightUnavailableError as _exc

        with pytest.raises(_exc):
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )

        # Exactly one log event emitted with the categorical name.
        assert len(captured) == 1, (
            f"expected exactly one log_safe event; got {len(captured)}: {captured!r}"
        )
        event_name, fields = captured[0]
        assert event_name == "apply.preflight_unavailable"
        assert fields == {"reason": "psutil_missing"}, (
            f"log fields must be exactly {{'reason': 'psutil_missing'}}; got {fields!r}"
        )

    def test_apply_dry_run_does_not_consult_preflight(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``--check-only`` (dry-run) bypasses the MSACCESS preflight entirely.

        Per design §6 matrix: ``--check-only skips``. A preflight
        failure (psutil missing) MUST NOT prevent the operator from
        running a read-only compare.
        """
        events = _events_recorder()

        def raise_unavailable() -> list[int]:
            events["events"].append("preflight_called")
            raise RuntimeError("should not be called on dry-run")

        monkeypatch.setattr(
            "migration.apply.check_msaccess_running", raise_unavailable
        )
        _patch_apply_seams(monkeypatch, events=events, executor_behavior="empty")

        result = apply_legacy_to_web(
            FakeLocalBackend(),
            "animal",
            legacy_path="/dummy/legacy.accdb",
            dry_run=True,
            lock_path=tmp_path / "migration.lock",
        )

        assert result.applied == 0
        assert result.errors == []
        # The preflight seam was never invoked.
        assert "preflight_called" not in events["events"]

    def test_preflight_failure_does_not_acquire_lock_or_read_legacy(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A preflight failure short-circuits BEFORE lock acquisition and reads.

        Belt-and-braces: the apply pipeline aborts on preflight
        failure BEFORE the bootstrap, lock, snapshot, or legacy
        executor. The bootstrap is also skipped (the preflight
        runs AFTER bootstrap but BEFORE lock in PR3 ordering).
        """
        from migration import MsAccessPreflightUnavailableError

        events = _events_recorder()

        # Apply patch first so the seam set is in place, then OVERRIDE
        # the check_msaccess_running seam with the raising fake.
        # Order matters: _patch_apply_seams monkeypatches
        # ``check_msaccess_running`` to its own no-op fake; the
        # explicit ``setattr`` below replaces it.
        _patch_apply_seams(monkeypatch, events=events, executor_behavior="empty")

        def raise_unavailable() -> list[int]:
            events["events"].append("preflight_called")
            raise MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            )

        monkeypatch.setattr(
            "migration.apply.check_msaccess_running", raise_unavailable
        )

        with pytest.raises(MsAccessPreflightUnavailableError):
            apply_legacy_to_web(
                FakeLocalBackend(),
                "animal",
                legacy_path="/dummy/legacy.accdb",
                lock_path=tmp_path / "migration.lock",
            )

        e = events["events"]
        assert "preflight_called" in e
        assert "acquire_lock" not in e
        assert "release_lock" not in e
        assert "executor" not in e
        # Snapshot was not written (preflight aborted first).
        assert "write_snapshot" not in e
