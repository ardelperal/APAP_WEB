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

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # ``_LocalBackendLike`` lives in ``migration.apply`` (kept there because
    # it is the structural type of the public ``apply_legacy_to_web``
    # signature). Re-imported for type checking only.
    # stub adapter in #671 is the placeholder; see web_reader_stub.
    # migration package is being rewritten in #8.
    from migration.apply import _LocalBackendLike  # type: ignore[attr-defined]  # noqa: F401







class _LockContext:
    """Wraps ``acquire_lock`` / ``release_lock`` in a context manager.

    Stdlib ``contextlib.AbstractContextManager`` would do, but the
    dataclass-shaped object reads cleaner at the apply call site.

    Skips the lock entirely in ``dry_run`` mode — the operator can
    re-run ``apply --check-only`` freely without locking out a real
    apply.
    """

    def __init__(
        self,
        _client: _LocalBackendLike,  # type: ignore[attr-defined]  # see #8
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
        # Lazy-import so test monkeypatches on
        # migration.apply.acquire_lock flow through.
        from migration.apply import acquire_lock
        acquire_lock(self._lock_path)
        self._acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._acquired:
            # Release even on the error path (Hard Rule 8 + the
            # apply slice's "lock always released" contract).
            try:
                # Lazy-import for the same reason as acquire_lock.
                from migration.apply import release_lock
                release_lock(self._lock_path)
            except Exception:  # noqa: BLE001 — never mask the original exc
                pass


def _resolve_default_lock_path() -> Path:
    """Resolve the lock path when the caller did not pass one.

    Mirrors ``migration.cli._resolve_lock_path`` — same env-var
    convention (``APAP_MIGRATION_DIR``), same default
    (``./migration/migration.lock``). Kept as a separate helper so
    ``migration.cli`` does not have to import from this module and we
    don't create a circular dependency.
    """
    import os

    migration_dir = os.environ.get("APAP_MIGRATION_DIR", "./migration")
    return Path(migration_dir) / "migration.lock"


def _resolve_default_snapshot_path() -> Path:
    """Resolve the snapshot path when the caller did not pass one.

    Same ``APAP_MIGRATION_DIR`` convention as the lock path. The
    snapshot lives next to the lock file and the partial-apply
    evidence so the operator's mental model is "everything the apply
    run touched lives in ``APAP_MIGRATION_DIR``".
    """
    return _resolve_default_lock_path().with_name("migration.lock_snapshot.json")


def _resolve_default_partial_path() -> Path:
    """Resolve the partial-apply evidence path when the caller did not pass one."""
    return _resolve_default_lock_path().with_name("migration.partial_apply.json")





__all__ = [
    "_LockContext",
    "_resolve_default_lock_path",
    "_resolve_default_partial_path",
    "_resolve_default_snapshot_path",
]
