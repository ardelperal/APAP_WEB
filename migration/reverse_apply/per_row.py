"""Per-row hot path for the reverse applier.

The reverse applier's per-row logic:

1. Map web row → legacy-row shape via :func:`_web_to_legacy_row`.
2. Look up the existing legacy row from the pre-computed
   ``legacy_by_key`` snapshot (one bulk read at the start of
   the run; the diff is bounded by ``< 5.000`` rows × ``< 10``
   columns per design §5).
3. If absent → INSERT (rare; happy path for newly-added web rows).
4. If present and equal → skip (no-op).
5. If present and different → UPDATE + ``sync.applied`` audit log.
6. For derived columns: if the web-side ``current_state`` differs
   from the prior forward-derived state, emit a ``LIFECYCLE_REVERSED``
   event. The derivation engine is NOT invoked on this path.
7. For ``preserve`` columns (web-only shadow, e.g. ``DNI``):
   advance the shadow row's ``last_legacy_snapshot_at``; never
   write ``preserved_value``.

Side-effects per row:

- One row INSERT/UPDATE against legacy (via the write seam).
- One ``log_safe("sync.applied", direction="web->legacy", ...)``
  per applied row.
- Per-row ``record_dni_collision`` invocations on preserve
  columns with no legacy equivalent.
- Per-row ``LIFECYCLE_REVERSED`` events when a derived column
  changed in web between forward and reverse apply.
- Per-row ``needs_review`` shadow rows when the legacy write
  returns rowcount=0 (drift detection).
"""

from __future__ import annotations

from typing import Any

from app.core import logging as logging_mod
from migration import legacy_reader as legacy_reader_mod
from migration.apply import _SAFE_TABLE_NAME, _safe_table
from migration.dni_collision import DniCollisionCounter
from migration.reverse_apply.io_helpers import (
    _case_insensitive_get,
    _compute_source_hash,
    _web_to_legacy_row,
)
from migration.reverse_apply.types import SqlExecutor


def _reverse_apply_one_row(
    *,
    client: SqlExecutor,
    mapping: Any,
    web_row: dict[str, Any],
    legacy_path: str,
    legacy_columns: tuple[str, ...],
    web_table: str,
    dry_run: bool,
    legacy_by_key: dict[str, dict[str, Any]],
    dni_collision_counter: DniCollisionCounter | None,
) -> str:
    """Apply one web row to legacy. Returns ``"applied"`` or ``"skipped"``.

    Uses module attribute lookup for the cross-module helpers
    (``_emit_reversed_lifecycle_events_for_changed_derived``,
    ``_advance_preserve_shadow_state``, ``_record_drift_needs_review``)
    so the existing test atoms that monkeypatch
    ``migration.apply_reverse._emit_reversed_lifecycle_events_for_changed_derived``
    see their patched callable. See the PR6 fix commit (e69aa2b)
    for the monkeypatchability discipline.
    """
    import migration.apply_reverse as apply_reverse_shim

    natural_key_value = _case_insensitive_get(web_row, mapping.key_field)
    if natural_key_value is None:
        raise ValueError(
            f"web row missing natural key {mapping.key_field!r}: {web_row!r}"
        )
    legacy_pk = str(natural_key_value)

    legacy_payload = _web_to_legacy_row(web_row, mapping)

    existing = legacy_by_key.get(legacy_pk)
    if existing is None:
        lower_target = legacy_pk.lower()
        for k, row in legacy_by_key.items():
            if k.lower() == lower_target:
                existing = row
                break

    if existing is None:
        # No legacy row yet → INSERT in legacy.
        if dry_run:
            return "applied"  # counted, not written
        _insert_legacy_row(
            legacy_path=legacy_path,
            legacy_table=mapping.legacy_table,
            legacy_payload=legacy_payload,
            natural_key=mapping.legacy_key,
            natural_key_value=legacy_pk,
        )

        # Advance the shadow-state per-row regardless of branch.
        apply_reverse_shim._advance_preserve_shadow_state(
            client=client,
            mapping=mapping,
            web_row=web_row,
            legacy_pk=legacy_pk,
            direction="web-to-legacy",
            dni_collision_counter=dni_collision_counter,
        )

        logging_mod.log_safe(
            "sync.applied",
            table=web_table,
            pk=legacy_pk,
            direction="web->legacy",
            source_hash=_compute_source_hash(legacy_payload),
            target_hash=None,
            op="INSERT",
            dry_run=False,
            actor="apply_reverse",
        )
        return "applied"

    # Row exists — compare the canonical mapped dict.
    target_payload = {col: existing.get(col) for col in legacy_payload}
    target_hash = _compute_source_hash(target_payload)
    new_hash = _compute_source_hash(legacy_payload)

    # Derived-column override detection runs BEFORE the skip check.
    apply_reverse_shim._emit_reversed_lifecycle_events_for_changed_derived(
        client=client,
        mapping=mapping,
        existing_legacy_row=existing,
        web_row=web_row,
        legacy_pk=legacy_pk,
    )

    # Advance the preserve-column shadow state for EVERY web row.
    apply_reverse_shim._advance_preserve_shadow_state(
        client=client,
        mapping=mapping,
        web_row=web_row,
        legacy_pk=legacy_pk,
        direction="web-to-legacy",
        dni_collision_counter=dni_collision_counter,
    )

    if new_hash == target_hash:
        return "skipped"

    # Divergence → UPDATE the legacy row.
    if dry_run:
        return "applied"  # counted, not written
    legacy_rowcount = _update_legacy_row(
        legacy_path=legacy_path,
        legacy_table=mapping.legacy_table,
        legacy_payload=legacy_payload,
        natural_key=mapping.legacy_key,
        natural_key_value=legacy_pk,
    )

    # Drift detection (rowcount=0 → needs_review).
    if legacy_rowcount == 0:
        apply_reverse_shim._record_drift_needs_review(
            client=client,
            mapping=mapping,
            web_row=web_row,
            legacy_pk=legacy_pk,
            source_hash=new_hash,
            target_hash=target_hash,
        )

    logging_mod.log_safe(
        "sync.applied",
        table=web_table,
        pk=legacy_pk,
        direction="web->legacy",
        source_hash=new_hash,
        target_hash=target_hash,
        op="UPDATE",
        dry_run=False,
        rowcount=legacy_rowcount,
        actor="apply_reverse",
    )
    return "applied"


def _insert_legacy_row(
    *,
    legacy_path: str,
    legacy_table: str,
    legacy_payload: dict[str, Any],
    natural_key: str,
    natural_key_value: str,
) -> None:
    """INSERT a new row in legacy via the write seam."""
    safe_table = _safe_table(legacy_table)
    cols = [
        c for c in legacy_payload if _SAFE_TABLE_NAME.match(c) and c != natural_key
    ]
    if not cols:
        raise ValueError(
            f"no safe columns to INSERT into {legacy_table}; payload={legacy_payload!r}"
        )
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    # noqa S608: ``safe_table`` pasa por ``_safe_table()``; las columnas se
    # filtran por ``_SAFE_TABLE_NAME``; los valores van como bind params
    # ``?``. Sin operandos de request. Issue #387.
    sql = f"INSERT INTO {safe_table} ({col_list}) VALUES ({placeholders})"  # noqa: S608
    params = [legacy_payload[c] for c in cols]
    legacy_reader_mod._execute_legacy_write(legacy_path, sql, params)


def _update_legacy_row(
    *,
    legacy_path: str,
    legacy_table: str,
    legacy_payload: dict[str, Any],
    natural_key: str,
    natural_key_value: str,
) -> int:
    """UPDATE the legacy row matching ``natural_key`` with ``legacy_payload``.

    Returns the write-seam rowcount (``int``). When no mapped
    writeable columns exist (a future PR may extend to derived
    payload; today's M2 reverse path is a no-op), returns ``0`` so
    the caller can route the row to ``needs_review`` without
    issuing a no-op SQL.
    """
    safe_table = _safe_table(legacy_table)
    safe_key = _safe_table(natural_key)
    cols = [c for c in legacy_payload if _SAFE_TABLE_NAME.match(c) and c != natural_key]
    if not cols:
        return 0
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    # noqa S608: ``safe_table`` y ``safe_key`` pasan por ``_safe_table()``;
    # las columnas del SET se filtran por ``_SAFE_TABLE_NAME``; los valores
    # van como bind params ``?``. Sin operandos de request. Issue #387.
    sql = f"UPDATE {safe_table} SET {set_clause} WHERE {safe_key} = ?"  # noqa: S608
    params = [legacy_payload[c] for c in cols] + [natural_key_value]
    return int(
        legacy_reader_mod._execute_legacy_write(legacy_path, sql, params)
    )


__all__ = [
    "_insert_legacy_row",
    "_reverse_apply_one_row",
    "_update_legacy_row",
]
