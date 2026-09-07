"""Internal helpers for ``migration.apply`` (module-size split).

The private ``_``-prefixed helpers and supporting classes that
``apply.py``'s ``apply_legacy_to_web`` pipeline uses live here,
so the parent module stays under the 700-line AGENTS.md
rule 21 budget. The public API (``apply_legacy_to_web``) is
unchanged; ``migration.apply`` re-imports the helpers via
``from migration.apply_helpers import ...`` so callers inside
the apply code keep the same name resolution.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # ``_LocalBackendLike`` lives in ``migration.apply`` (kept there because
    # it is the structural type of the public ``apply_legacy_to_web``
    # signature). Re-imported for type checking only.
    # stub adapter in #671 is the placeholder; see web_reader_stub.
    # migration package is being rewritten in #8.
    from migration.apply import SqlExecutor  # noqa: F401


from migration.apply_helpers import SourceDriftError
from migration.lock_snapshot import Snapshot, detect_drift


def _write_or_check_snapshot(
    *,
    legacy_path: str,
    photos_dir_path: Path | str | None,
    snapshot_path: Path,
) -> Snapshot:
    """Compute hashes, drift-check against the existing snapshot, then write.

    Raises ``SourceDriftError`` if a previous snapshot exists with
    different fingerprints; in that case the previous snapshot is
    preserved on disk (no destructive overwrite). Returns the newly
    written ``Snapshot`` so callers can inspect ``started_at`` if
    needed.
    """
    # Lazy-import so test monkeypatches on
    # ``migration.apply.compute_accdb_hash`` flow through.
    from migration.apply import compute_accdb_hash, compute_photos_dir_hash
    accdb_hash = compute_accdb_hash(legacy_path)
    photos_manifest = compute_photos_dir_hash(photos_dir_path)

    # Lazy-import so test monkeypatches on
    # ``migration.apply.read_snapshot`` flow through.
    from migration.apply import read_snapshot
    previous = read_snapshot(snapshot_path)
    if previous is not None:
        # Build a prospective snapshot with the SAME shape that
        # ``write_snapshot`` would produce, then compare ignoring the
        # ``started_at`` timestamp (it always advances). Empty / missing
        # sources produce ``EMPTY_SHA256`` consistently so a fresh
        # empty source matches a previous empty-source snapshot.
        prospective = Snapshot(
            schema_version=previous.schema_version,
            direction="legacy-to-web",
            started_at=datetime.now(UTC),
            accdb_sha256=accdb_hash,
            photos_dir_sha256=photos_manifest.sha256,
            photos_file_count=photos_manifest.file_count,
            photos_total_bytes=photos_manifest.total_bytes,
        )
        drift = detect_drift(previous, prospective)
        if drift.drifted:
            raise SourceDriftError(
                detail=(
                    "Source drift detected between previous and current "
                    "apply run. accdb_sha256_changed="
                    f"{drift.accdb_sha256_changed}, "
                    "photos_dir_sha256_changed="
                    f"{drift.photos_dir_sha256_changed}, "
                    f"photos_file_count_delta={drift.photos_file_count_delta}, "
                    f"photos_total_bytes_delta={drift.photos_total_bytes_delta}. "
                    "Refusing to apply; review the source files."
                ),
                accdb_sha256_changed=drift.accdb_sha256_changed,
                photos_dir_sha256_changed=drift.photos_dir_sha256_changed,
                photos_file_count_delta=drift.photos_file_count_delta,
                photos_total_bytes_delta=drift.photos_total_bytes_delta,
            )

    # Lazy-import so test monkeypatches on
    # migration.apply.write_snapshot flow through.
    from migration.apply import write_snapshot
    return write_snapshot(
        snapshot_path,
        direction="legacy-to-web",
        accdb_sha256=accdb_hash,
        photos_manifest=photos_manifest,
    )





__all__ = ["_write_or_check_snapshot"]
