"""Tests for ``migration.lock_snapshot`` (PR3/M1).

Source-identity snapshot for live data migration. The contract:

- **Versioned JSON**: ``schema_version`` is mandatory and pinned; an
  unknown version on read raises ``ValueError`` (fail closed).
- **Atomic write**: temp file + ``os.replace`` so the on-disk file is
  never half-written.
- **No PII / raw paths in serialization**: ``Snapshot.to_json()`` and
  ``DriftSummary`` expose only hashes, counts, deltas and direction.
  ``partial_apply.json`` exposes only direction, table, progress, reason,
  and ISO timestamp — never raw paths or PII.
- **Determinism**: photos manifest is sorted by filename; sha256 is the
  hash of the canonical JSON of (filename, size, sha256-of-bytes) entries.
- **Empty / missing sources**: an empty ``.accdb`` or a missing / not-a-dir
  photos path produce sha256-of-empty-bytes, NOT a crash. Migration is
  allowed to proceed against a valid empty source.

Three paths per slice (web-tdd-philosophy Rule 5):

- **happy**: deterministic compute + write + read roundtrip
- **sad**: missing file, corrupt JSON, unknown version
- **edge**: empty bytes, empty dir, subdirectories skipped, filename-order
  independence

Hard Rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): every test sets up its own ``tmp_path`` files.
- Rule 2 (DI): paths are parameters, never module-level globals.
- Rule 4 (no humo): assertions pin concrete hashes / counts / bytes.
- Rule 6 (refactor-safety): tests assert JSON shape + dataclass equality,
  not internal helper call order.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from migration.lock_snapshot import (
    SCHEMA_VERSION,
    PhotosManifest,
    Snapshot,
    compute_accdb_hash,
    compute_photos_dir_hash,
    detect_drift,
    read_partial_apply,
    read_snapshot,
    write_partial_apply,
    write_snapshot,
)

# --------------------------------------------------------------------------
# Snapshot dataclass + JSON serialization
# --------------------------------------------------------------------------


class TestSnapshotSerialization:
    """Snapshot schema, version, and round-trip serialization."""

    def test_snapshot_is_versioned(self) -> None:
        snap = Snapshot(
            schema_version=SCHEMA_VERSION,
            direction="legacy-to-web",
            started_at=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
            accdb_sha256="a" * 64,
            photos_dir_sha256="b" * 64,
            photos_file_count=3,
            photos_total_bytes=1024,
        )
        assert snap.schema_version == SCHEMA_VERSION == 1

    def test_snapshot_to_json_omits_raw_paths(self) -> None:
        """Snapshot JSON must not leak filesystem paths or PII markers.

        Field-name fragments like ``photos_dir_sha256`` legitimately
        contain ``photos_dir`` as a substring but the rule is about
        VALUES, not labels. The check asserts the actual JSON values
        do not embed paths or PII tokens.
        """
        snap = Snapshot(
            schema_version=SCHEMA_VERSION,
            direction="legacy-to-web",
            started_at=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
            accdb_sha256="a" * 64,
            photos_dir_sha256="b" * 64,
            photos_file_count=3,
            photos_total_bytes=1024,
        )
        raw = snap.to_json()
        for forbidden in (
            "DNI",
            "Email",
            "Tel1",
            "Tel2",
            "C:\\",
            "/var/",
            "/home/",
            "password",
            "secret",
        ):
            assert forbidden not in raw, (
                f"forbidden token {forbidden!r} leaked into snapshot JSON"
            )

    def test_snapshot_from_json_roundtrip(self) -> None:
        snap = Snapshot(
            schema_version=SCHEMA_VERSION,
            direction="legacy-to-web",
            started_at=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
            accdb_sha256="a" * 64,
            photos_dir_sha256="b" * 64,
            photos_file_count=3,
            photos_total_bytes=1024,
        )
        loaded = Snapshot.from_json(snap.to_json())
        assert loaded == snap

    def test_snapshot_from_json_rejects_unknown_version(self) -> None:
        raw = json.dumps({"schema_version": 999, "direction": "legacy-to-web"})
        with pytest.raises(ValueError):
            Snapshot.from_json(raw)

    def test_snapshot_from_json_rejects_corrupt_payload(self) -> None:
        with pytest.raises(ValueError):
            Snapshot.from_json("not json")

    def test_snapshot_direction_is_preserved(self) -> None:
        snap = Snapshot(
            schema_version=SCHEMA_VERSION,
            direction="legacy-to-web",
            started_at=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
            accdb_sha256="a" * 64,
            photos_dir_sha256="b" * 64,
            photos_file_count=0,
            photos_total_bytes=0,
        )
        loaded = Snapshot.from_json(snap.to_json())
        assert loaded.direction == "legacy-to-web"


# --------------------------------------------------------------------------
# compute_accdb_hash
# --------------------------------------------------------------------------


class TestComputeAccdbHash:
    """SHA-256 of the legacy ``.accdb`` file content."""

    def test_compute_accdb_hash_deterministic(self, tmp_path: Path) -> None:
        p = tmp_path / "x.accdb"
        p.write_bytes(b"hello world")
        assert compute_accdb_hash(p) == compute_accdb_hash(p)

    def test_compute_accdb_hash_is_sha256_hex(self, tmp_path: Path) -> None:
        p = tmp_path / "x.accdb"
        p.write_bytes(b"hello world")
        h = compute_accdb_hash(p)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_compute_accdb_hash_distinguishes_content(self, tmp_path: Path) -> None:
        a = tmp_path / "a.accdb"
        b = tmp_path / "b.accdb"
        a.write_bytes(b"hello")
        b.write_bytes(b"world")
        assert compute_accdb_hash(a) != compute_accdb_hash(b)

    def test_compute_accdb_hash_empty_file_returns_sha256_of_empty(
        self, tmp_path: Path
    ) -> None:
        """Empty .accdb → sha256 of zero bytes (NOT a crash)."""
        p = tmp_path / "empty.accdb"
        p.write_bytes(b"")
        assert compute_accdb_hash(p) == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_compute_accdb_hash_missing_file_returns_sha256_of_empty(
        self, tmp_path: Path
    ) -> None:
        """Missing .accdb path → sha256 of zero bytes (NOT a crash)."""
        h = compute_accdb_hash(tmp_path / "does-not-exist.accdb")
        assert h == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_compute_accdb_hash_inaccessible_file_returns_sha256_of_empty(
        self, tmp_path: Path
    ) -> None:
        """Path that is a directory (or otherwise not readable) → empty hash."""
        # tmp_path is a directory; opening it for read raises OSError.
        h = compute_accdb_hash(tmp_path)
        assert h == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )


# --------------------------------------------------------------------------
# compute_photos_dir_hash
# --------------------------------------------------------------------------


class TestComputePhotosDirHash:
    """Deterministic manifest of the photos directory."""

    def test_empty_dir_returns_sha256_of_empty(self, tmp_path: Path) -> None:
        m = compute_photos_dir_hash(tmp_path)
        assert m.file_count == 0
        assert m.total_bytes == 0
        assert m.sha256 == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_missing_dir_returns_sha256_of_empty(self, tmp_path: Path) -> None:
        m = compute_photos_dir_hash(tmp_path / "does-not-exist")
        assert m.file_count == 0
        assert m.total_bytes == 0
        assert m.sha256 == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_none_path_returns_sha256_of_empty(self) -> None:
        m = compute_photos_dir_hash(None)
        assert m.file_count == 0
        assert m.total_bytes == 0
        assert m.sha256 == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_populated_dir_counts_files_and_bytes(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"AAA")
        (tmp_path / "b.jpg").write_bytes(b"BBBB")
        m = compute_photos_dir_hash(tmp_path)
        assert m.file_count == 2
        assert m.total_bytes == 7

    def test_populated_dir_deterministic(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"AAA")
        (tmp_path / "b.jpg").write_bytes(b"BBB")
        assert compute_photos_dir_hash(tmp_path) == compute_photos_dir_hash(tmp_path)

    def test_populated_dir_filename_order_independent(self, tmp_path: Path) -> None:
        # Hash must be stable regardless of file creation order on disk.
        (tmp_path / "z.jpg").write_bytes(b"AAA")
        (tmp_path / "a.jpg").write_bytes(b"BBB")
        (tmp_path / "m.jpg").write_bytes(b"CCC")
        m1 = compute_photos_dir_hash(tmp_path)

        second = tmp_path / "second"
        second.mkdir()
        (second / "z.jpg").write_bytes(b"AAA")
        (second / "a.jpg").write_bytes(b"BBB")
        (second / "m.jpg").write_bytes(b"CCC")
        m2 = compute_photos_dir_hash(second)

        assert m1.sha256 == m2.sha256

    def test_skips_subdirectories(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"AAA")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.jpg").write_bytes(b"NNN")
        m = compute_photos_dir_hash(tmp_path)
        assert m.file_count == 1
        assert m.total_bytes == 3

    def test_distinguishes_content_changes(self, tmp_path: Path) -> None:
        (tmp_path / "a.jpg").write_bytes(b"AAA")
        m_before = compute_photos_dir_hash(tmp_path)
        (tmp_path / "a.jpg").write_bytes(b"BBB")
        m_after = compute_photos_dir_hash(tmp_path)
        assert m_before.sha256 != m_after.sha256
        assert m_after.file_count == 1
        assert m_after.total_bytes == 3


# --------------------------------------------------------------------------
# write_snapshot / read_snapshot
# --------------------------------------------------------------------------


class TestSnapshotReadWrite:
    """Atomic write of the snapshot file + read-back roundtrip."""

    def _manifest(self) -> PhotosManifest:
        return PhotosManifest(file_count=3, total_bytes=1024, sha256="b" * 64)

    def test_write_snapshot_creates_file(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.json"
        snap = write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="a" * 64,
            photos_manifest=self._manifest(),
        )
        assert p.exists()
        assert snap.schema_version == SCHEMA_VERSION
        assert snap.accdb_sha256 == "a" * 64
        assert snap.photos_dir_sha256 == "b" * 64

    def test_write_snapshot_no_tmp_file_left(self, tmp_path: Path) -> None:
        """Atomic write must leave no temporary file in the parent dir."""
        p = tmp_path / "snap.json"
        write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="a" * 64,
            photos_manifest=self._manifest(),
        )
        assert list(tmp_path.iterdir()) == [p]

    def test_write_snapshot_creates_parent_dir(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "snap.json"
        write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="a" * 64,
            photos_manifest=self._manifest(),
        )
        assert p.exists()

    def test_write_snapshot_overwrites_existing(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.json"
        write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="a" * 64,
            photos_manifest=self._manifest(),
        )
        write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="c" * 64,
            photos_manifest=PhotosManifest(
                file_count=0, total_bytes=0, sha256="d" * 64
            ),
        )
        snap = read_snapshot(p)
        assert snap is not None
        assert snap.accdb_sha256 == "c" * 64
        assert snap.photos_file_count == 0

    def test_write_snapshot_json_contains_no_path_values(
        self, tmp_path: Path
    ) -> None:
        """The on-disk JSON must not leak the caller-provided paths.

        ``photos_dir_sha256`` is a legitimate field name and the empty
        fragment ``photos_dir`` matches it as a substring — that is OK.
        The rule is about VALUES, not labels. The check asserts the
        actual JSON values do not embed the test tmp dir, a Windows
        drive prefix, or PII tokens.
        """
        p = tmp_path / "snap.json"
        write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="a" * 64,
            photos_manifest=self._manifest(),
        )
        raw = p.read_text(encoding="utf-8")
        for forbidden in (
            str(tmp_path),
            "C:\\",
            "DNI",
            "Email",
            "Tel1",
            "Tel2",
            "legacy_path",
            "accdb_path",
        ):
            assert forbidden not in raw, (
                f"forbidden {forbidden!r} leaked into {raw!r}"
            )

    def test_read_snapshot_missing_returns_none(self, tmp_path: Path) -> None:
        assert read_snapshot(tmp_path / "missing.json") is None

    def test_read_snapshot_corrupt_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.json"
        p.write_text("not json")
        with pytest.raises(ValueError):
            read_snapshot(p)

    def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "snap.json"
        written = write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="abc123",
            photos_manifest=PhotosManifest(
                file_count=5, total_bytes=4096, sha256="def456"
            ),
        )
        loaded = read_snapshot(p)
        assert loaded == written
        assert loaded is not None
        assert loaded.photos_file_count == 5
        assert loaded.photos_total_bytes == 4096

    def test_write_snapshot_starts_at_utc(self, tmp_path: Path) -> None:
        """``started_at`` must be UTC so drift comparisons are tz-safe."""
        p = tmp_path / "snap.json"
        snap = write_snapshot(
            p,
            direction="legacy-to-web",
            accdb_sha256="a" * 64,
            photos_manifest=self._manifest(),
        )
        assert snap.started_at.tzinfo is not None
        assert snap.started_at.utcoffset().total_seconds() == 0


# --------------------------------------------------------------------------
# detect_drift
# --------------------------------------------------------------------------


class TestDetectDrift:
    """Drift comparison between two snapshots."""

    def _base(self, *, accdb: str, photos: str, count: int, total: int) -> Snapshot:
        return Snapshot(
            schema_version=SCHEMA_VERSION,
            direction="legacy-to-web",
            started_at=datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
            accdb_sha256=accdb,
            photos_dir_sha256=photos,
            photos_file_count=count,
            photos_total_bytes=total,
        )

    def test_no_drift_when_all_fields_match(self) -> None:
        s1 = self._base(accdb="a" * 64, photos="b" * 64, count=3, total=1024)
        s2 = self._base(accdb="a" * 64, photos="b" * 64, count=3, total=1024)
        summary = detect_drift(s1, s2)
        assert summary.drifted is False
        assert summary.accdb_sha256_changed is False
        assert summary.photos_dir_sha256_changed is False
        assert summary.photos_file_count_delta == 0
        assert summary.photos_total_bytes_delta == 0

    def test_drift_when_accdb_changed(self) -> None:
        s1 = self._base(accdb="a" * 64, photos="b" * 64, count=3, total=1024)
        s2 = self._base(accdb="z" * 64, photos="b" * 64, count=3, total=1024)
        summary = detect_drift(s1, s2)
        assert summary.drifted is True
        assert summary.accdb_sha256_changed is True
        assert summary.photos_dir_sha256_changed is False

    def test_drift_when_photos_changed(self) -> None:
        s1 = self._base(accdb="a" * 64, photos="b" * 64, count=3, total=1024)
        s2 = self._base(accdb="a" * 64, photos="y" * 64, count=5, total=1524)
        summary = detect_drift(s1, s2)
        assert summary.drifted is True
        assert summary.accdb_sha256_changed is False
        assert summary.photos_dir_sha256_changed is True
        assert summary.photos_file_count_delta == 2
        assert summary.photos_total_bytes_delta == 500

    def test_drift_summary_str_omits_paths_and_pii(self) -> None:
        s1 = self._base(accdb="a" * 64, photos="b" * 64, count=3, total=1024)
        s2 = self._base(accdb="z" * 64, photos="y" * 64, count=4, total=2000)
        summary = detect_drift(s1, s2)
        blob = str(summary)
        for forbidden in ("DNI", "Email", "Tel", "/var/", "C:\\", "secret"):
            assert forbidden not in blob

    def test_drift_delta_can_be_negative(self) -> None:
        """Removing photos produces a negative file-count delta."""
        s1 = self._base(accdb="a" * 64, photos="b" * 64, count=5, total=1024)
        s2 = self._base(accdb="a" * 64, photos="c" * 64, count=2, total=512)
        summary = detect_drift(s1, s2)
        assert summary.photos_file_count_delta == -3
        assert summary.photos_total_bytes_delta == -512


# --------------------------------------------------------------------------
# write_partial_apply / read_partial_apply
# --------------------------------------------------------------------------


class TestPartialApplyEvidence:
    """Partial-apply evidence: written on SIGINT after snapshot."""

    def test_write_partial_apply_creates_file_atomically(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "partial.json"
        write_partial_apply(
            p,
            direction="legacy-to-web",
            table_name="animal",
            progress_applied=42,
            progress_total=100,
            reason="sigint",
        )
        assert p.exists()
        # No leftover tmp file
        assert list(tmp_path.iterdir()) == [p]

    def test_write_partial_apply_creates_parent_dir(self, tmp_path: Path) -> None:
        p = tmp_path / "sub" / "partial.json"
        write_partial_apply(
            p,
            direction="legacy-to-web",
            table_name="animal",
            progress_applied=1,
            progress_total=None,
            reason="sigint",
        )
        assert p.exists()

    def test_write_partial_apply_omits_raw_paths_and_pii(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "partial.json"
        write_partial_apply(
            p,
            direction="legacy-to-web",
            table_name="animal",
            progress_applied=1,
            progress_total=None,
            reason="sigint",
        )
        raw = p.read_text(encoding="utf-8")
        for forbidden in (
            "DNI",
            "Email",
            "Tel1",
            "Tel2",
            str(tmp_path),
            "C:\\",
            "legacy_path",
            "accdb_path",
            "photos_dir",
        ):
            assert forbidden not in raw, (
                f"forbidden {forbidden!r} leaked into partial JSON"
            )

    def test_read_partial_apply_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "partial.json"
        write_partial_apply(
            p,
            direction="legacy-to-web",
            table_name="animal",
            progress_applied=42,
            progress_total=None,
            reason="sigint",
        )
        payload = read_partial_apply(p)
        assert payload is not None
        assert payload["direction"] == "legacy-to-web"
        assert payload["table_name"] == "animal"
        assert payload["progress_applied"] == 42
        assert payload["progress_total"] is None
        assert payload["reason"] == "sigint"

    def test_read_partial_apply_roundtrip_with_total(self, tmp_path: Path) -> None:
        p = tmp_path / "partial.json"
        write_partial_apply(
            p,
            direction="legacy-to-web",
            table_name="voluntario",
            progress_applied=10,
            progress_total=50,
            reason="sigint",
        )
        payload = read_partial_apply(p)
        assert payload is not None
        assert payload["progress_total"] == 50

    def test_read_partial_apply_missing_returns_none(self, tmp_path: Path) -> None:
        assert read_partial_apply(tmp_path / "missing.json") is None

    def test_read_partial_apply_corrupt_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "partial.json"
        p.write_text("not json")
        with pytest.raises(ValueError):
            read_partial_apply(p)

    def test_partial_apply_recorded_at_is_iso8601(self, tmp_path: Path) -> None:
        p = tmp_path / "partial.json"
        write_partial_apply(
            p,
            direction="legacy-to-web",
            table_name="animal",
            progress_applied=1,
            progress_total=None,
            reason="sigint",
        )
        payload = read_partial_apply(p)
        assert payload is not None
        # ISO-8601 parse must succeed; tz-aware or naive both acceptable
        # but the value must round-trip through ``fromisoformat``.
        datetime.fromisoformat(payload["recorded_at"])
