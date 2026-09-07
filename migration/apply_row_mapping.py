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

import hashlib
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # ``_LocalBackendLike`` lives in ``migration.apply`` (kept there because
    # it is the structural type of the public ``apply_legacy_to_web``
    # signature). Re-imported for type checking only.
    # stub adapter in #671 is the placeholder; see web_reader_stub.
    # migration package is being rewritten in #8.
    from migration.apply import _LocalBackendLike  # type: ignore[attr-defined]  # noqa: F401
    from migration.apply_per_row import _VoluntariosIndex  # noqa: F401


from migration.apply_helpers import _apply_value_transform, _resolve_fk_value


def _legacy_to_web_row(
    legacy_row: dict[str, Any],
    mapping: Any,
    client: _LocalBackendLike,
    vol_index: _VoluntariosIndex | None = None,
) -> dict[str, Any]:
    """Map a legacy ``dict`` to its web-column ``dict``.

    Walks the ``mapping.columns`` list and emits only the columns with a
    non-null ``legacy_column``. Web-only columns (``legacy_column=None``,
    e.g. ``DNI`` on ``voluntarios``) are skipped -- they are owned by
    the web side and the shadow-state handles their reconciliation.

    For columns with ``transform: fk_lookup``, resolves the legacy free-text
    value to a web UUID via :func:`_resolve_fk_value`.  volontario columns
    use fuzzy matching when the YAML declares ``fuzzy_match: true``.
    """
    out: dict[str, Any] = {}
    for col in mapping.columns:
        # FK columns (transform: fk_lookup) always need resolution,
        # regardless of whether their YAML column declares legacy_column.
        # The YAML uses legacy_column=None for FK columns that have no direct
        # legacy equivalent (the legacy value lives in fk_lookups[].legacy_column).
        # Check this FIRST so we don't skip FK columns at the next gate.
        if col.transform == "fk_lookup":
            lookup_spec = next(
                (lk for lk in mapping.fk_lookups if lk.name == col.lookup),
                None,
            )
            if lookup_spec is None:
                continue
            # Prefer col.legacy_column; fall back to lookup_spec.legacy_column
            # (for FK columns that only declare the legacy column in fk_lookups).
            legacy_src = col.legacy_column or lookup_spec.legacy_column
            resolved = _resolve_fk_value(
                legacy_row.get(legacy_src),
                lookup_table=lookup_spec.lookup_table,
                lookup_key=lookup_spec.lookup_legacy_key,
                client=client,
                vol_index=vol_index,
                fuzzy_match=lookup_spec.fuzzy_match,
                fuzzy_threshold=lookup_spec.fuzzy_threshold,
                optional=lookup_spec.optional,
            )
            out[col.web_column] = resolved
        elif col.legacy_column is None:
            # Web-only non-FK column (id, fecha_alta, DNI, ...) -- handled
            # by the SQL default or the shadow-state.
            continue
        else:
            raw = legacy_row.get(col.legacy_column)
            out[col.web_column] = _apply_value_transform(col.transform, raw)
    return out


def _compute_source_hash(row: dict[str, Any]) -> str:
    """SHA-256 hex of the canonical JSON of ``row``.

    The source hash is the audit-log fingerprint of what the legacy
    side presented. Stable across Python runs (sorted keys, no
    whitespace) so a re-run produces the same hash and idempotency
    is observable.
    """
    payload = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- Apply entry point --------------------------------------------------





__all__ = [
    "_compute_source_hash",
    "_legacy_to_web_row",
]
