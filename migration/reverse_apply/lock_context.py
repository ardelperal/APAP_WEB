from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.core.data_access import SqlExecutor  # noqa: F401
"""Lock context + snapshot helpers + path resolution for the reverse applier.

Mirrors the forward applier's ``migration.apply._LockContext`` and
``_write_or_check_snapshot`` so the reverse path uses the same
fail-closed drift-detection contract (PR3 fail-closed; do not
overwrite a drifted snapshot).

The reverse applier has its own COPY of ``_write_or_check_snapshot``
(deliberately duplicated from ``migration.apply``) because the
direction is baked in (``web-to-legacy``) and the forward applier
cannot accept a direction parameter without growing past its
700-line BASELINE (AGENTS.md rule 21 ratchet).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from migration import (
    acquire_lock,
    release_lock,
)
from migration.apply import _safe_table  # noqa: F401 — used for the snapshot path defaults
from migration.lock_snapshot import (
    Snapshot,
    compute_accdb_hash,
    compute_photos_dir_hash,
    detect_drift,
    read_snapshot,
    write_snapshot,
)
from migration.reverse_apply.types import SqlExecutor

DIRECTION_WEB_TO_LEGACY = "web-to-legacy"


def _skip_bootstrap_for_reverse(*_args: Any, **_kwargs: Any) -> None:
    """Reverse apply does NOT bootstrap M0 infra.

    The forward applier runs :func:`bootstrap_m0_infrastructure` to
    ensure the shadow table + private ``apap-photos`` bucket exist.
    The reverse applier does not touch either — storage writes are
    forward-only, and the shadow-table DDL is forward-only too (the
    forward applier's atomic ``CREATE TABLE IF NOT EXISTS`` runs
    there).
    """


class _LockContext:
    """Tiny context manager wrapping ``acquire_lock`` / ``release_lock``.

    Mirror of ``migration.apply._LockContext``. Skips the lock
    entirely in ``dry_run`` mode so the operator can re-run
    ``--check-only`` freely.
    """

    def __init__(
        self,
        _client: SqlExecutor,
        lock_path: Path | None,
        *,
        dry_run: bool,
    ) -> None:
        self._lock_path = lock_path or _resolve_default_lock_path()
        self._dry_run = dry_run
        self._acquired = False

    def __enter__(self) -> _LockContext:
        if self._dry_run:
            return self
        acquire_lock(self._lock_path)
        self._acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._acquired:
            try:
                release_lock(self._lock_path)
            except Exception:  # noqa: BLE001 — never mask the original exc
                pass


def _write_or_check_snapshot(
    *,
    legacy_path: str,
    photos_dir_path: Path | str | None,
    snapshot_path: Path,
    direction: str,
) -> Snapshot:
    """Compute hashes, drift-check, write. Mirror of the forward helper.

    PR3 fail-closed contract preserved: when a previous snapshot's
    ``.accdb_sha256`` / photos manifest disagrees with the freshly
    computed values, raise :class:`SourceDriftError` and leave the
    previous snapshot intact on disk.
    """
    accdb_hash = compute_accdb_hash(legacy_path)
    photos_manifest = compute_photos_dir_hash(photos_dir_path)

    previous = read_snapshot(snapshot_path)
    if previous is not None:
        prospective = Snapshot(
            schema_version=previous.schema_version,
            direction=direction,
            started_at=datetime.now(UTC),
            accdb_sha256=accdb_hash,
            photos_dir_sha256=photos_manifest.sha256,
            photos_file_count=photos_manifest.file_count,
            photos_total_bytes=photos_manifest.total_bytes,
        )
        drift = detect_drift(previous, prospective)
        if drift.drifted:
            from migration.apply import SourceDriftError

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

    return write_snapshot(
        snapshot_path,
        direction=direction,
        accdb_sha256=accdb_hash,
        photos_manifest=photos_manifest,
    )


def _resolve_default_lock_path() -> Path:
    """``<APAP_MIGRATION_DIR>/migration.lock``. Mirrors the forward helper."""
    import os

    return Path(os.environ.get("APAP_MIGRATION_DIR", "./migration")) / "migration.lock"


def _resolve_default_snapshot_path() -> Path:
    """``<APAP_MIGRATION_DIR>/migration.lock_snapshot.json``."""
    return _resolve_default_lock_path().with_name("migration.lock_snapshot.json")


def _resolve_default_partial_path() -> Path:
    """``<APAP_MIGRATION_DIR>/migration.partial_apply.json``."""
    return _resolve_default_lock_path().with_name("migration.partial_apply.json")


def _resolve_default_sync_state_path() -> Path:
    """``<APAP_MIGRATION_DIR>/sync_state.json``.

    Reverse applier advances ``tables[table].last_sync_at`` AFTER
    the legacy writes commit. The file lives at the same canonical
    path the diff engine + forward applier read, so an operator
    re-run of either direction sees the same cursor.
    """
    return _resolve_default_lock_path().parent / "sync_state.json"


__all__ = [
    "DIRECTION_WEB_TO_LEGACY",
    "_LockContext",
    "_resolve_default_lock_path",
    "_resolve_default_partial_path",
    "_resolve_default_snapshot_path",
    "_resolve_default_sync_state_path",
    "_skip_bootstrap_for_reverse",
    "_write_or_check_snapshot",
]
