"""Source-identity snapshot for live data migration (PR3/M1).

The snapshot is the durable, auditable record of what the migration
operator's disk looked like when an ``apply`` started. It is the
contract that powers:

- **Drift detection between runs**: the operator can compare today's
  ``migration.lock_snapshot.json`` with yesterday's and refuse to apply
  silently if the source has changed under their feet.
- **Post-mortem after SIGINT**: the snapshot pins the SHA-256 of the
  ``.accdb`` and the photos directory; if the apply was interrupted,
  ``migration.partial_apply.json`` records where we stopped so the
  operator can decide whether to resume or roll back.

Hard contracts (web-tdd-philosophy + AGENTS.md §18):

- **Versioned JSON**: ``schema_version`` is mandatory. An unknown
  version on read raises ``ValueError`` (fail closed). Callers can
  evolve the schema later by bumping ``SCHEMA_VERSION`` and adding a
  migration in ``from_json``.
- **Atomic write**: temp file + ``os.replace`` so the on-disk file is
  never half-written. The temp file is unlinked if the write fails.
- **No PII / raw paths in serialization**: the JSON exposes only
  hashes, counts, direction, ISO timestamps. No filesystem paths,
  no operator identifiers, no PII column values.
- **Deterministic**: the photos manifest is sorted by filename; the
  manifest SHA-256 is the hash of the canonical JSON of
  ``(filename, size, sha256-of-bytes)`` entries. Same dir → same hash.
- **Empty / missing sources are valid**: an empty ``.accdb`` or a
  missing photos directory produces the SHA-256 of zero bytes. The
  migration is allowed to proceed against a valid empty source —
  fail-closed would block legitimate first-runs and idempotent replays.

This module owns ONLY the snapshot and partial-apply files. It does
NOT acquire locks, talk to the web DB, or invoke the legacy executor.
Those concerns belong to ``migration.apply``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION: int = 1
"""Pinned snapshot schema version.

Bump when the JSON shape changes in a way that breaks older readers.
``Snapshot.from_json`` rejects unknown versions so a deploy with a
newer writer cannot silently corrupt an older reader.
"""

#: SHA-256 of zero bytes — the deterministic hash for an empty source.
#: Pre-computed once so tests do not have to hard-code the value.
EMPTY_SHA256: str = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True, slots=True)
class PhotosManifest:
    """Deterministic manifest of a photos directory.

    The manifest is the auditable summary of the photos directory at
    snapshot time. The ``sha256`` is the hash of the canonical JSON of
    (filename, size, sha256-of-bytes) entries sorted by filename, so
    two identical directories produce the same hash regardless of OS
    iteration order.

    A missing / inaccessible / empty directory produces the
    ``EMPTY_SHA256`` with ``file_count=0`` and ``total_bytes=0``. The
    migration can still proceed against a valid empty source.
    """

    file_count: int
    total_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Versioned record of the source files a migration started against.

    The dataclass is the contract between ``write_snapshot`` and
    ``detect_drift``. It carries only what is safe to serialize: hashes,
    counts, direction, ISO timestamp. No raw paths, no operator
    identifiers, no PII column values.

    ``schema_version`` is the on-disk version; bumping it forces
    ``from_json`` to reject older writes.
    """

    schema_version: int
    direction: str
    started_at: datetime
    accdb_sha256: str
    photos_dir_sha256: str
    photos_file_count: int
    photos_total_bytes: int

    def to_json(self) -> str:
        """Serialize the snapshot to JSON (UTF-8, ASCII-safe).

        ``asdict`` flattens nested dataclasses; ``datetime`` is
        serialized as ISO-8601 via the ``default`` callback; ``tuple``
        (none here) would auto-serialize as ``list``.
        """
        return json.dumps(
            asdict(self),
            default=_json_default,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> Snapshot:
        """Deserialize a snapshot from JSON.

        Raises ``ValueError`` if:

        - the JSON is malformed,
        - the root is not an object,
        - ``schema_version`` is missing or unknown (fail closed),
        - any required field is missing or of the wrong type.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Snapshot JSON is malformed: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"Snapshot root must be a JSON object, got {type(data).__name__}"
            )
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"Unknown snapshot schema_version={version!r}; "
                f"this reader expects {SCHEMA_VERSION}"
            )
        try:
            started_at_raw = data["started_at"]
            started_at = datetime.fromisoformat(started_at_raw)
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            return cls(
                schema_version=version,
                direction=str(data["direction"]),
                started_at=started_at,
                accdb_sha256=str(data["accdb_sha256"]),
                photos_dir_sha256=str(data["photos_dir_sha256"]),
                photos_file_count=int(data["photos_file_count"]),
                photos_total_bytes=int(data["photos_total_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Snapshot JSON missing or invalid field: {exc}") from exc


@dataclass(frozen=True, slots=True)
class DriftSummary:
    """Result of comparing two snapshots.

    ``drifted`` is ``True`` if either source-identity field changed.
    The numeric deltas expose the magnitude of the change for the
    operator (e.g. ``photos_file_count_delta``). The summary exposes
    no raw paths and no PII.
    """

    drifted: bool
    accdb_sha256_changed: bool
    photos_dir_sha256_changed: bool
    photos_file_count_delta: int
    photos_total_bytes_delta: int


# --------------------------------------------------------------------------
# compute_accdb_hash
# --------------------------------------------------------------------------


def compute_accdb_hash(path: Path | str) -> str:
    """SHA-256 hex of the ``.accdb`` file at ``path``.

    The hash is over the file content read in 64 KiB chunks so a multi-MB
    database does not allocate a single giant buffer. Returns the
    SHA-256 of zero bytes (the EMPTY_SHA256 constant) when the path is
    missing, unreadable, a directory, or an empty file. This is the
    deterministic fingerprint of a valid empty source, NOT a crash.
    """
    p = Path(path)
    try:
        if not p.is_file():
            return EMPTY_SHA256
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return EMPTY_SHA256


# --------------------------------------------------------------------------
# compute_photos_dir_hash
# --------------------------------------------------------------------------


def compute_photos_dir_hash(path: Path | str | None) -> PhotosManifest:
    """Deterministic manifest of the photos directory at ``path``.

    Walks ``path`` non-recursively (top-level entries only) and emits a
    manifest of ``(filename, size, sha256-of-bytes)`` entries sorted by
    filename. The manifest's ``sha256`` is the hash of the canonical
    JSON of those entries, so two operators with the same directory
    content produce the same hash regardless of OS file iteration
    order.

    Subdirectories are counted as zero — only files participate in the
    manifest. Missing / inaccessible / ``None`` paths return an empty
    manifest with ``EMPTY_SHA256``.
    """
    if path is None:
        return PhotosManifest(file_count=0, total_bytes=0, sha256=EMPTY_SHA256)
    p = Path(path)
    if not p.is_dir():
        return PhotosManifest(file_count=0, total_bytes=0, sha256=EMPTY_SHA256)
    try:
        entries: list[dict[str, Any]] = []
        total = 0
        for child in sorted(p.iterdir(), key=lambda x: x.name):
            if not child.is_file():
                continue
            try:
                size = child.stat().st_size
                with child.open("rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                # A file we cannot read is silently skipped; the
                # migration can still proceed with a partial manifest.
                # A subsequent apply will re-hash and may differ; the
                # drift detector will surface the change.
                continue
            entries.append(
                {"name": child.name, "size": size, "sha256": file_hash}
            )
            total += size
        # An empty directory produces the EMPTY_SHA256 (not the hash of
        # "[]"). This matches the contract used by ``compute_accdb_hash``
        # for an empty .accdb: a valid empty source has a single,
        # well-known fingerprint — the SHA-256 of zero bytes — so the
        # drift detector can identify "no source" without ambiguity.
        if not entries:
            return PhotosManifest(
                file_count=0, total_bytes=0, sha256=EMPTY_SHA256
            )
        manifest_hash = hashlib.sha256(
            json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return PhotosManifest(
            file_count=len(entries), total_bytes=total, sha256=manifest_hash
        )
    except OSError:
        return PhotosManifest(file_count=0, total_bytes=0, sha256=EMPTY_SHA256)


# --------------------------------------------------------------------------
# write_snapshot / read_snapshot
# --------------------------------------------------------------------------


def write_snapshot(
    path: Path | str,
    *,
    direction: str,
    accdb_sha256: str,
    photos_manifest: PhotosManifest,
) -> Snapshot:
    """Write the versioned snapshot to ``path`` atomically.

    The write is atomic from the reader's perspective: either the new
    snapshot is fully present at ``path`` or the previous content
    (or no content) is still there. A temp file is created in the
    same parent directory and ``os.replace``-d into place; if the
    write raises, the temp file is unlinked so no garbage accumulates.

    The parent directory is created if missing.

    Returns the ``Snapshot`` that was written (its ``started_at`` is
    the wall-clock at the moment of the call).
    """
    snap = Snapshot(
        schema_version=SCHEMA_VERSION,
        direction=direction,
        started_at=datetime.now(UTC),
        accdb_sha256=accdb_sha256,
        photos_dir_sha256=photos_manifest.sha256,
        photos_file_count=photos_manifest.file_count,
        photos_total_bytes=photos_manifest.total_bytes,
    )
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    raw = snap.to_json()
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-snapshot-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp_name, p)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return snap


def read_snapshot(path: Path | str) -> Snapshot | None:
    """Read the snapshot at ``path`` or return ``None`` if missing.

    Returns ``None`` when the file does not exist OR the read raised an
    OSError (e.g. permission denied). Raises ``ValueError`` for a
    present-but-malformed file so an operator can distinguish "no
    snapshot yet" from "snapshot but corrupt" — the apply preflight
    reacts differently to each.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return None
    return Snapshot.from_json(raw)


# --------------------------------------------------------------------------
# detect_drift
# --------------------------------------------------------------------------


def detect_drift(previous: Snapshot, current: Snapshot) -> DriftSummary:
    """Compare ``previous`` with ``current`` and return a summary.

    Direction is excluded from the drift comparison (the same direction
    is assumed across consecutive runs of the same apply command).
    Schema version differences are also excluded — readers should
    have rejected mismatched versions at read time.
    """
    return DriftSummary(
        drifted=(
            previous.accdb_sha256 != current.accdb_sha256
            or previous.photos_dir_sha256 != current.photos_dir_sha256
        ),
        accdb_sha256_changed=previous.accdb_sha256 != current.accdb_sha256,
        photos_dir_sha256_changed=(
            previous.photos_dir_sha256 != current.photos_dir_sha256
        ),
        photos_file_count_delta=(
            current.photos_file_count - previous.photos_file_count
        ),
        photos_total_bytes_delta=(
            current.photos_total_bytes - previous.photos_total_bytes
        ),
    )


# --------------------------------------------------------------------------
# write_partial_apply / read_partial_apply
# --------------------------------------------------------------------------


def write_partial_apply(
    path: Path | str,
    *,
    direction: str,
    table_name: str,
    progress_applied: int,
    progress_total: int | None,
    reason: str,
) -> None:
    """Write the partial-apply evidence file at ``path`` atomically.

    Recorded when an apply is interrupted (SIGINT) AFTER the snapshot
    was written but BEFORE the run completed. Operator-visible
    evidence: NOT a destructive cleanup. The next ``apply`` detects
    this file and fails closed until the operator cleans it up.

    The JSON contains direction, table name, progress counters, the
    reason, and an ISO-8601 timestamp. No raw paths, no operator
    identifiers, no PII column values.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "direction": direction,
        "table_name": table_name,
        "progress_applied": int(progress_applied),
        "progress_total": (
            int(progress_total) if progress_total is not None else None
        ),
        "reason": str(reason),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-partial-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp_name, p)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_partial_apply(path: Path | str) -> dict[str, Any] | None:
    """Return the partial-apply payload at ``path`` or ``None`` if missing.

    Raises ``ValueError`` on a present-but-malformed file so an
    operator can distinguish "no evidence yet" from "evidence but
    corrupt".
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Partial-apply evidence at {p} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"Partial-apply evidence at {p} must be a JSON object, "
            f"got {type(data).__name__}"
        )
    return data


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    """JSON encoder default for non-standard types (datetime only)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


__all__ = [
    "DriftSummary",
    "EMPTY_SHA256",
    "PhotosManifest",
    "SCHEMA_VERSION",
    "Snapshot",
    "compute_accdb_hash",
    "compute_photos_dir_hash",
    "detect_drift",
    "read_partial_apply",
    "read_snapshot",
    "write_partial_apply",
    "write_snapshot",
]
