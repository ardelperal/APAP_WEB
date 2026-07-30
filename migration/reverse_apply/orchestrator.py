"""Reverse-apply orchestrator: ``apply_web_to_legacy`` entry point.

The orchestrator owns:

- The public ``apply_web_to_legacy(client, table_name, *, ...)`` API.
- The bulk-legacy-snapshot read (one page; the reverse path is
  bounded by diff size, not table size).
- The MSACCESS pre-flight + partial-apply guard (mirrors the
  forward applier's fail-closed contract).
- The per-row loop (delegates to ``per_row._reverse_apply_one_row``).
- The ``sync_state.json`` advance (AFTER the per-row loop
  completes; on failure, the file is left byte-identical to the
  pre-apply state via the in-memory pre-bytes snapshot).

Module attribute lookup — not name binding — is used for the
``logging_mod.log_safe`` calls and the cross-module helper
references so tests can monkeypatch the seams (the PR6 fix commit
e69aa2b established this discipline for ``logging_mod`` and
``semantic_events_mod``).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from app.core import logging as logging_mod
from migration import (
    MsAccessPreflightUnavailableError,
    check_msaccess_running,
)
from migration import legacy_reader as legacy_reader_mod
from migration.apply import ApplyResult, _safe_table
from migration.bootstrap import bootstrap_m0_infrastructure
from migration.dni_collision import DniCollisionCounter
from migration.legacy_reader import LegacyWriteCommitFailed
from migration.lock_snapshot import read_partial_apply
from migration.mappings import load_mapping
from migration.reporting import MigrationReport
from migration.reverse_apply.io_helpers import _build_web_select_sql
from migration.reverse_apply.lock_context import (
    DIRECTION_WEB_TO_LEGACY,
    _LockContext,
    _resolve_default_lock_path,
    _resolve_default_partial_path,
    _resolve_default_snapshot_path,
    _resolve_default_sync_state_path,
    _write_or_check_snapshot,
)
from migration.reverse_apply.per_row import (  # noqa: F401 — accessed via globals()
    _reverse_apply_one_row,
)
from migration.sync_state import (
    load_sync_state,
    save_sync_state,
    update_last_sync_at,
)

# --- helpers -----------------------------------------------------------


def _rollback_sync_state_if_dirty(
    resolved_sync_state_path: Path,
    sync_state_pre_bytes: bytes | None,
) -> None:
    """Roll ``sync_state.json`` back to ``sync_state_pre_bytes`` if it
    was modified (bytes differ).  Silently ignores OSError during the
    write so rollback failures nevermask the original exception."""
    if sync_state_pre_bytes is None:
        return
    if not resolved_sync_state_path.exists():
        return
    current = resolved_sync_state_path.read_bytes()
    if current != sync_state_pre_bytes:
        try:
            resolved_sync_state_path.write_bytes(sync_state_pre_bytes)
        except OSError:
            pass


def _run_msaccess_preflight(dry_run: bool) -> None:
    """Run the MSAccess pre-flight check.

    Raises ``MsAccessRunningError`` if another MSAccess process is
    running; raises ``MsAccessPreflightUnavailableError`` if psutil is
    unavailable (fail-closed — operator must resolve the preflight
    condition before applying).
    """
    if dry_run:
        return
    try:
        msaccess_pids = check_msaccess_running()
    except MsAccessPreflightUnavailableError as preflight_exc:
        logging_mod.log_safe(
            "apply.preflight_unavailable",
            reason=preflight_exc.reason,
        )
        raise
    if msaccess_pids:
        from migration.apply import MsAccessRunningError

        raise MsAccessRunningError(
            pids=msaccess_pids,
            detail=(
                f"Cannot run apply while MSACCESS.EXE is running "
                f"(pids={msaccess_pids}). Close the legacy Access "
                "frontend and retry."
            ),
        )


def _load_web_rows(
    client: Any,
    web_table: str,
    web_columns: tuple[str, ...],
    web_snapshot: dict[str, list[dict[str, Any]]] | None,
    safe: str,
) -> list[dict[str, Any]] | ApplyResult:
    """Load web rows from ``web_snapshot`` or by querying the client.

    Returns an error ApplyResult (with ``applied=0, skipped=0``) if the
    SQL query fails, so callers can return early.
    """
    if web_snapshot is not None:
        return list(web_snapshot.get(web_table, []))
    sql = _build_web_select_sql(web_table, web_columns)
    try:
        return client.execute_sql(sql)
    except Exception as exc:  # noqa: BLE001 — last-resort guard
        return ApplyResult(
            table_name=safe,
            applied=0,
            skipped=0,
            errors=[f"{safe}: web query failed: {exc}"],
        )


def _load_legacy_snapshot(
    legacy_path: str,
    mapping: Any,
    legacy_columns: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Load the legacy snapshot and index it by natural key (case-insensitive).

    Raises on read failure so the operator sees a categorical error.
    """
    from migration.reverse_apply.io_helpers import _case_insensitive_get

    legacy_by_key: dict[str, dict[str, Any]] = {}
    try:
        for _table_name, rows in legacy_reader_mod.load_legacy_snapshot_batched(
            legacy_path,
            [
                legacy_reader_mod.TableSpec(
                    legacy_table=mapping.legacy_table,
                    columns=legacy_columns or ("*",),
                    where=None,
                )
            ],
        ):
            for legacy_row in rows:
                key_value = _case_insensitive_get(legacy_row, mapping.legacy_key)
                if key_value is None:
                    continue
                legacy_by_key[str(key_value)] = dict(legacy_row)
    except Exception as exc:  # noqa: BLE001 — surface to operator stream
        logging_mod.log_safe(
            "apply.legacy_read_failed",
            reason=type(exc).__name__,
        )
        raise
    return legacy_by_key


def _check_partial_apply_guard(
    dry_run: bool,
    resolved_partial_path: Path,
) -> None:
    """Raise ``PartialApplyInterruptedError`` if a partial-apply marker
    exists from a previous interrupted run."""
    if dry_run:
        return
    existing_partial = read_partial_apply(resolved_partial_path)
    if existing_partial is not None:
        from migration.apply import PartialApplyInterruptedError

        raise PartialApplyInterruptedError(
            detail=(
                f"Previous apply was interrupted; review "
                f"{resolved_partial_path} and remove it to retry. "
                f"Evidence: progress_applied="
                f"{existing_partial.get('progress_applied')!r}, "
                f"reason={existing_partial.get('reason')!r}"
            ),
            evidence=existing_partial,
        )


def _write_snapshot_and_load_sync_state(
    *,
    dry_run: bool,
    legacy_path: str,
    photos_dir_path: Path | str | None,
    resolved_snapshot_path: Path,
    resolved_sync_state_path: Path,
) -> tuple[bool, Any, bytes | None]:
    """Write the legacy snapshot and load sync_state.

    Returns ``(snapshot_written, sync_state_loaded, sync_state_pre_bytes)``.
    Silently returns ``(False, None, None)`` on error so the outer flow
    continues with a best-effort snapshot.
    """
    snapshot_written = False
    sync_state_loaded: Any = None
    sync_state_pre_bytes: bytes | None = None

    if not dry_run:
        _write_or_check_snapshot(
            legacy_path=legacy_path,
            photos_dir_path=photos_dir_path,
            snapshot_path=resolved_snapshot_path,
            direction=DIRECTION_WEB_TO_LEGACY,
        )
        snapshot_written = True

    if not dry_run and resolved_sync_state_path.exists():
        sync_state_loaded = load_sync_state(resolved_sync_state_path)
        sync_state_pre_bytes = resolved_sync_state_path.read_bytes()

    return snapshot_written, sync_state_loaded, sync_state_pre_bytes


def _handle_interrupt(
    applied: int,
    snapshot_written: bool,
    resolved_partial_path: Path,
    resolved_sync_state_path: Path,
    sync_state_pre_bytes: bytes | None,
    safe: str,
) -> NoReturn:
    """Handle ``KeyboardInterrupt``: write partial-apply marker and roll back."""
    if snapshot_written:
        from migration.lock_snapshot import write_partial_apply

        write_partial_apply(
            resolved_partial_path,
            direction=DIRECTION_WEB_TO_LEGACY,
            table_name=safe,
            progress_applied=applied,
            progress_total=None,
            reason="sigint",
        )
    _rollback_sync_state_if_dirty(resolved_sync_state_path, sync_state_pre_bytes)
    raise  # re-raise so the interrupt propagates to the caller


def _handle_exception(
    resolved_sync_state_path: Path,
    sync_state_pre_bytes: bytes | None,
) -> NoReturn:
    """Handle generic exception: roll back sync_state and re-raise."""
    _rollback_sync_state_if_dirty(resolved_sync_state_path, sync_state_pre_bytes)
    raise


def _save_sync_state_if_needed(
    sync_state_loaded: Any,
    resolved_sync_state_path: Path,
    web_table: str,
    applied: int,
    dry_run: bool,
) -> tuple[list[str], bool]:
    """Save sync_state.json if rows were applied.

    Returns ``(errors, sync_state_saved)`` so the caller knows whether a
    rollback is warranted on outer exceptions.
    """
    errors: list[str] = []
    if dry_run or applied <= 0 or sync_state_loaded is None:
        return errors, False
    try:
        update_last_sync_at(sync_state_loaded, web_table, datetime.now(UTC))
        save_sync_state(sync_state_loaded, resolved_sync_state_path)
        return errors, True
    except Exception as exc:  # noqa: BLE001 — never mask row errors
        logging_mod.log_safe(
            "sync_state.rollback",
            table=web_table,
            reason=str(exc),
        )
        errors.append(
            f"{web_table}: sync_state rollback "
            f"(legacy writes succeeded; re-run to advance the cursor): {exc}"
        )
        return errors, False


def _process_per_row_loop(
    *,
    client: Any,
    mapping: Any,
    legacy_path: str,
    legacy_columns: tuple[str, ...],
    web_table: str,
    web_rows: list[dict[str, Any]],
    legacy_by_key: dict[str, dict[str, Any]],
    dni_collision_counter: DniCollisionCounter | None,
    dry_run: bool,
) -> tuple[int, int, list[str]]:
    """Run the per-row apply loop.

    Returns ``(applied, skipped, errors)``.
    Raises ``LegacyWriteCommitFailed`` on commit failure so the caller
    can propagate the categorical error.

    Uses module-attribute lookup (``globals()``) so that tests patching
    ``orchestrator_mod._reverse_apply_one_row`` hit this function too
    (the plain import creates a closure binding that bypasses the patch).
    """
    applied = 0
    skipped = 0
    errors: list[str] = []

    for web_row in web_rows:
        try:
            # Module-attribute lookup: resolves the patched binding at call
            # time so tests can intercept through orchestrator_mod patching.
            outcome = globals()["_reverse_apply_one_row"](
                client=client,
                mapping=mapping,
                web_row=web_row,
                legacy_path=legacy_path,
                legacy_columns=legacy_columns,
                web_table=web_table,
                dry_run=dry_run,
                legacy_by_key=legacy_by_key,
                dni_collision_counter=dni_collision_counter,
            )
        except LegacyWriteCommitFailed:
            raise
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            natural_key = (
                web_row.get(mapping.key_field) if mapping.key_field else None
            )
            errors.append(
                f"{mapping.legacy_table}: unexpected error on "
                f"{natural_key!r}: {exc}"
            )
            continue
        if outcome == "applied":
            applied += 1
        else:
            skipped += 1

    return applied, skipped, errors


# --- public API -------------------------------------------------------


def apply_web_to_legacy(
    client: Any,
    table_name: str,
    *,
    legacy_path: str,
    web_snapshot: dict[str, list[dict[str, Any]]] | None = None,
    dry_run: bool = False,
    lock_path: Path | None = None,
    snapshot_path: Path | None = None,
    partial_path: Path | None = None,
    photos_dir_path: Path | str | None = None,
    dni_collision_counter: DniCollisionCounter | None = None,
    migration_report: MigrationReport | None = None,
    sync_state_path: Path | None = None,
) -> ApplyResult:
    """Bulk-apply web rows for one table into the legacy ``.accdb``.

    The kwarg-only signature is preserved verbatim from PR6 fix
    commit e69aa2b; the F5 contract keeps the same surface so the
    14 reverse-apply atoms and the 5 round-trip atoms continue to
    call it unchanged.
    """
    safe = _safe_table(table_name)
    mapping = load_mapping(safe)
    web_table = _safe_table(mapping.web_table)

    resolved_lock_path = lock_path or _resolve_default_lock_path()
    resolved_snapshot_path = (
        Path(snapshot_path) if snapshot_path else _resolve_default_snapshot_path()
    )
    resolved_partial_path = (
        Path(partial_path) if partial_path else _resolve_default_partial_path()
    )
    resolved_sync_state_path = (
        Path(sync_state_path)
        if sync_state_path
        else _resolve_default_sync_state_path()
    )

    if not dry_run:
        bootstrap_m0_infrastructure(client)

    # --- partial-apply guard ------------------------------------------
    _check_partial_apply_guard(dry_run, resolved_partial_path)

    # --- MSAccess pre-flight -----------------------------------------
    _run_msaccess_preflight(dry_run)

    # --- load web rows ----------------------------------------------
    legacy_columns: tuple[str, ...] = tuple(
        c.legacy_column for c in mapping.columns if c.legacy_column
    )
    web_columns: tuple[str, ...] = tuple(c.web_column for c in mapping.columns)

    web_rows_or_error = _load_web_rows(
        client, web_table, web_columns, web_snapshot, safe
    )
    # Propagate early-return on web-query failure.
    if isinstance(web_rows_or_error, ApplyResult):
        return web_rows_or_error
    web_rows: list[dict[str, Any]] = web_rows_or_error

    # --- load legacy snapshot ----------------------------------------
    legacy_by_key = _load_legacy_snapshot(legacy_path, mapping, legacy_columns)

    # --- apply rows -------------------------------------------------
    lock_ctx = _LockContext(client, resolved_lock_path, dry_run=dry_run)
    # snapshot_written / sync_state_loaded / sync_state_pre_bytes: initialized
    # before the try so KeyboardInterrupt from inside _process_per_row_loop
    # still has bindable names in this scope.
    snapshot_written = False
    sync_state_loaded: Any = None
    sync_state_pre_bytes: bytes | None = None
    applied = 0
    skipped = 0
    errors: list[str] = []

    try:
        with lock_ctx:
            snapshot_written, sync_state_loaded, sync_state_pre_bytes = (
                _write_snapshot_and_load_sync_state(
                    dry_run=dry_run,
                    legacy_path=legacy_path,
                    photos_dir_path=photos_dir_path,
                    resolved_snapshot_path=resolved_snapshot_path,
                    resolved_sync_state_path=resolved_sync_state_path,
                )
            )

            applied, skipped, errors = _process_per_row_loop(
                client=client,
                mapping=mapping,
                legacy_path=legacy_path,
                legacy_columns=legacy_columns,
                web_table=web_table,
                web_rows=web_rows,
                legacy_by_key=legacy_by_key,
                dni_collision_counter=dni_collision_counter,
                dry_run=dry_run,
            )

            sync_errors, _ = _save_sync_state_if_needed(
                sync_state_loaded,
                resolved_sync_state_path,
                mapping.web_table,
                applied,
                dry_run,
            )
            errors.extend(sync_errors)

        if migration_report is not None:
            migration_report.counts.setdefault(safe, {})["count_web"] = len(web_rows)
            migration_report.collisions.setdefault(safe, {})[
                "preserve_advances"
            ] = (
                dni_collision_counter.value
                if dni_collision_counter is not None
                else 0
            )

        return ApplyResult(
            table_name=safe,
            applied=applied,
            skipped=skipped,
            errors=errors,
        )
    except KeyboardInterrupt:
        _handle_interrupt(
            applied,
            snapshot_written,
            resolved_partial_path,
            resolved_sync_state_path,
            sync_state_pre_bytes,
            safe,
        )
    except Exception:
        _handle_exception(resolved_sync_state_path, sync_state_pre_bytes)


__all__ = [
    "apply_web_to_legacy",
]


# Silence an unused-import lint for `os` (imported for symmetry with
# ``migration.apply._resolve_default_lock_path`` but not referenced
# directly here; the lock-context helper does the resolution).
_ = os
