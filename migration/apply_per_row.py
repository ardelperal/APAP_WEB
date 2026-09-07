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

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # ``_LocalBackendLike`` lives in ``migration.apply`` (kept there because
    # it is the structural type of the public ``apply_legacy_to_web``
    # signature). Re-imported for type checking only.
    # stub adapter in #671 is the placeholder; see web_reader_stub.
    # migration package is being rewritten in #8.
    from migration.apply import _LocalBackendLike  # type: ignore[attr-defined]  # noqa: F401


from app.core import logging as logging_mod
from migration.apply_helpers import _SAFE_TABLE_NAME, _safe_table, _VoluntariosIndex
from migration.apply_row_mapping import _compute_source_hash, _legacy_to_web_row
from migration.shadow_state import ShadowStateRepository


def _apply_one_row(
    *,
    client: _LocalBackendLike,
    mapping: Any,
    web_table: str,
    legacy_row: dict[str, Any],
    dry_run: bool,
    vol_index: _VoluntariosIndex | None = None,
) -> str:
    """Apply one legacy row and return ``"applied"`` or ``"skipped"``.

    Helper extracted from :func:`apply_legacy_to_web` so the per-row
    logic is unit-testable without the paging loop in the way. The
    return string is the row's outcome (``"applied"`` when an INSERT
    was emitted, ``"skipped"`` for either a no-op equality or a
    divergence recorded in the shadow table).
    """
    legacy_pk_value = legacy_row.get(mapping.legacy_key)
    if legacy_pk_value is None:
        # The legacy row has no natural key -- there is nothing to match
        # against the web side. Surface as an error so the CLI's error
        # count bumps.
        raise ValueError(
            f"legacy row missing natural key {mapping.legacy_key!r}: {legacy_row!r}"
        )
    legacy_pk = str(legacy_pk_value)

    source_hash = _compute_source_hash(legacy_row)
    web_row = _legacy_to_web_row(legacy_row, mapping, client, vol_index)

    existing = _fetch_web_row_by_key(client, mapping, legacy_pk)

    if existing is None:
        if dry_run:
            return "applied"  # counted, not written
        returned = _insert_web_row(client, web_table, web_row)
        logging_mod.log_safe(
            "sync.applied",
            table=web_table,
            pk=legacy_pk,
            direction="legacy->web",
            source_hash=source_hash,
            target_hash=None,
            op="INSERT",
            dry_run=False,
        )
        # Register the new row in the volontarios index so subsequent
        # rows (acogidas / adopciones) can resolve FKs via Level 2.
        # Only for the volontarios table; other tables contribute no
        # volontario name -> UUID entries.
        if vol_index is not None and mapping.web_table == "volontarios":
            web_uuid = returned[0]["id"] if returned else None
            if web_uuid:
                vol_index.record(str(legacy_pk_value), str(web_uuid))
        return "applied"

    # Row exists -- compare the canonical mapped dict.
    target_payload = {col: existing.get(col) for col in web_row}
    target_hash = _compute_source_hash(target_payload)
    if _compute_source_hash(web_row) == target_hash:
        return "skipped"

    # Divergence: record in the shadow table. We do NOT overwrite the
    # web row; the operator reconciles via ``reconcile --interactive``.
    if not dry_run:
        _record_shadow_divergence(
            client=client,
            table_name=mapping.web_table,
            legacy_pk=legacy_pk,
            web_pk=str(existing.get("id")) if existing.get("id") else None,
            source_hash=source_hash,
            target_hash=target_hash,
        )
        logging_mod.log_safe(
            "sync.applied",
            table=web_table,
            pk=legacy_pk,
            direction="legacy->web",
            source_hash=source_hash,
            target_hash=target_hash,
            op="NOOP_DIVERGENCE_RECORDED",
            dry_run=False,
        )
    return "skipped"


def _fetch_web_row_by_key(
    client: _LocalBackendLike, mapping: Any, legacy_pk: str
) -> dict[str, Any] | None:
    """Return the existing web row matching ``legacy_pk``, or ``None``.

    Looks up by the natural key column (``mapping.key_field``). The
    query is intentionally simple — equality on a single column —
    because the natural key for every spec in this slice is a single
    non-composite column (NCHIP, Voluntario, ...). A future PR can
    extend to composite keys (the materiales catalog already uses one).
    """
    key_col = _safe_table(mapping.key_field)
    table = _safe_table(mapping.web_table)
    sql = f"SELECT * FROM {table} WHERE {key_col} = $1 LIMIT 1"  # noqa: S608 ids validados
    rows = client.execute_sql(sql, [legacy_pk])
    return rows[0] if rows else None


def _insert_web_row(
    client: _LocalBackendLike, web_table: str, web_row: dict[str, Any]
) -> list[dict[str, Any]]:
    """INSERT ``web_row`` into ``web_table`` and return the ``RETURNING`` row.

    The SQL is constructed from the column list of ``web_row`` so the
    function works against any mapping without a per-table hand-coded
    INSERT. ``id`` (UUID) and timestamps (``fecha_alta``,
    ``updated_at``) are handled by the DB defaults (``DEFAULT
    gen_random_uuid()``, ``DEFAULT now()``) -- we just don't include
    them in the params if they're missing from the mapped row.

    Returns the rows from ``RETURNING id`` so callers can record the
    new web UUID (e.g. for FK index registration in VOL-04).
    """
    safe_table = _safe_table(web_table)
    cols = [c for c in web_row if _SAFE_TABLE_NAME.match(c)]
    if not cols:
        raise ValueError(f"no safe columns to INSERT into {web_table}")
    placeholders = ", ".join(f"${i + 1}" for i in range(len(cols)))
    cols_vals = f"({', '.join(cols)}) VALUES ({placeholders})"
    sql = f"INSERT INTO {safe_table} {cols_vals} RETURNING id"  # noqa: S608 ids validados
    params = [web_row[c] for c in cols]
    return client.execute_sql(sql, params)


def _record_shadow_divergence(
    *,
    client: _LocalBackendLike,
    table_name: str,
    legacy_pk: str,
    web_pk: str | None,
    source_hash: str,
    target_hash: str,
) -> None:
    """INSERT a divergence row into ``web_only_feature_shadow``.

    The shadow table is the durable audit trail: every disagreement
    between the legacy and web sides is recorded exactly once (the
    table's UNIQUE composite index — once added by a follow-up PR —
    will reject duplicate rows). The operator reconciles via
    ``migrate reconcile --interactive``.
    """
    safe = _safe_table(table_name)
    ShadowStateRepository(client).upsert(
        table_name=safe,
        legacy_pk=legacy_pk,
        web_pk=web_pk,
        web_column="__row__",
        preserved_value={"source_hash": source_hash, "target_hash": target_hash},
        strategy="preserve",
        reconciliation_status="needs_review",
    )


# --- Lock context manager -----------------------------------------------





__all__ = [
    "_apply_one_row",
    "_fetch_web_row_by_key",
    "_insert_web_row",
    "_record_shadow_divergence",
]
