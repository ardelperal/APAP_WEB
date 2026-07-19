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
from typing import Any

from app.core import logging as logging_mod
from migration import (
    MsAccessPreflightUnavailableError,
    check_msaccess_running,
)
from migration import legacy_reader as legacy_reader_mod
from migration.apply import ApplyResult, _safe_table
from migration.bootstrap import bootstrap_m0_infrastructure
from migration.dni_collision import DniCollisionCounter
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
from migration.reverse_apply.per_row import _reverse_apply_one_row
from migration.sync_state import (
    load_sync_state,
    save_sync_state,
    update_last_sync_at,
)


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

    if not dry_run:
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

    if not dry_run:
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

    legacy_columns: tuple[str, ...] = tuple(
        c.legacy_column for c in mapping.columns if c.legacy_column
    )
    web_columns: tuple[str, ...] = tuple(c.web_column for c in mapping.columns)

    if web_snapshot is None:
        sql = _build_web_select_sql(web_table, web_columns)
        try:
            web_rows = client.execute_sql(sql)
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            query_errors: list[str] = []
            query_errors.append(f"{mapping.web_table}: web query failed: {exc}")
            return ApplyResult(
                table_name=safe,
                applied=0,
                skipped=0,
                errors=query_errors,
            )
    else:
        web_rows = list(web_snapshot.get(mapping.web_table, []))

    legacy_by_key: dict[str, dict[str, Any]] = {}
    try:
        for _legacy_table_name, rows in legacy_reader_mod.load_legacy_snapshot_batched(
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
                from migration.reverse_apply.io_helpers import _case_insensitive_get

                key_value = _case_insensitive_get(legacy_row, mapping.legacy_key)
                if key_value is None:
                    continue
                legacy_by_key[str(key_value)] = dict(legacy_row)
    except Exception as exc:  # noqa: BLE001 — surface to the operator stream
        logging_mod.log_safe(
            "apply.legacy_read_failed",
            reason=type(exc).__name__,
        )
        raise

    lock_ctx = _LockContext(client, resolved_lock_path, dry_run=dry_run)
    snapshot_written = False
    errors: list[str] = []
    applied = 0
    skipped = 0

    sync_state_loaded: Any = None
    sync_state_pre_bytes: bytes | None = None

    try:
        with lock_ctx:
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

            for web_row in web_rows:
                try:
                    outcome = _reverse_apply_one_row(
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
                except Exception as exc:  # noqa: BLE001 — last-resort guard
                    natural_key = web_row.get(mapping.key_field) if mapping.key_field else None
                    errors.append(
                        f"{mapping.legacy_table}: unexpected error on "
                        f"{natural_key!r}: {exc}"
                    )
                    continue
                if outcome == "applied":
                    applied += 1
                else:
                    skipped += 1

            if not dry_run and applied > 0 and sync_state_loaded is not None:
                try:
                    update_last_sync_at(
                        sync_state_loaded,
                        mapping.web_table,
                        datetime.now(UTC),
                    )
                    save_sync_state(sync_state_loaded, resolved_sync_state_path)
                except Exception as exc:  # noqa: BLE001 — never mask row errors
                    logging_mod.log_safe(
                        "sync_state.rollback",
                        table=mapping.web_table,
                        reason=str(exc),
                    )
                    errors.append(
                        f"{mapping.web_table}: sync_state rollback "
                        f"(legacy writes succeeded; re-run to advance "
                        f"the cursor): {exc}"
                    )

        if migration_report is not None:
            migration_report.counts.setdefault(safe, {})["count_web"] = len(web_rows)
            migration_report.collisions.setdefault(safe, {})[
                "dni_collisions"
            ] = dni_collision_counter.value if dni_collision_counter is not None else 0

        return ApplyResult(
            table_name=safe,
            applied=applied,
            skipped=skipped,
            errors=errors,
        )
    except KeyboardInterrupt:
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
        if sync_state_pre_bytes is not None and resolved_sync_state_path.exists():
            current = resolved_sync_state_path.read_bytes()
            if current != sync_state_pre_bytes:
                try:
                    resolved_sync_state_path.write_bytes(sync_state_pre_bytes)
                except OSError:
                    pass
        raise
    except Exception:
        if sync_state_pre_bytes is not None and resolved_sync_state_path.exists():
            current = resolved_sync_state_path.read_bytes()
            if current != sync_state_pre_bytes:
                try:
                    resolved_sync_state_path.write_bytes(sync_state_pre_bytes)
                except OSError:
                    pass
        raise


__all__ = [
    "apply_web_to_legacy",
]


# Silence an unused-import lint for `os` (imported for symmetry with
# ``migration.apply._resolve_default_lock_path`` but not referenced
# directly here; the lock-context helper does the resolution).
_ = os
