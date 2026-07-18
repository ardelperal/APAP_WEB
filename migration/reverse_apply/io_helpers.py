"""Small I/O helpers for the reverse applier.

The reverse applier reads web rows (lowercase keys) and writes to
legacy tables (CamelCase keys). The YAML mapping stores CamelCase
names; web rows store lowercase. These helpers normalize that gap
without dragging in the per-row lifecycle logic.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _case_insensitive_get(row: dict[str, Any], key: str) -> Any:
    """Return ``row[key]`` ignoring case on the key lookup.

    The YAML mappings store column names in CamelCase (the legacy
    convention); the web row keys are lowercase. A naive
    ``row.get(key)`` returns ``None`` when the cases disagree, so
    the helper looks up the lowercase form AND any uppercase variant
    of ``key`` in the row. Returns ``None`` on miss.
    """
    if not row:
        return None
    direct = row.get(key)
    if direct is not None:
        return direct
    lower = key.lower()
    if row.get(lower) is not None:
        return row.get(lower)
    upper = key.upper()
    if row.get(upper) is not None:
        return row.get(upper)
    target = lower
    for k, v in row.items():
        if k.lower() == target:
            return v
    return None


def _web_to_legacy_row(web_row: dict[str, Any], mapping: Any) -> dict[str, Any]:
    """Map a web ``dict`` to its legacy-column ``dict``.

    Inverse of :func:`migration.apply._legacy_to_web_row`: walks the
    same ``mapping.columns`` list, but emits only the columns with a
    non-null ``legacy_column``. Web-only columns
    (``legacy_column=None``, e.g. ``DNI`` on ``voluntarios``) are
    skipped — legacy has no column to receive them, and the
    :func:`record_dni_collision` helper routes the per-row
    collision to the shadow table via the DI seam.

    Column lookups are case-insensitive: the YAML keeps CamelCase
    names (``Voluntario``, ``NCHIP``) for legacy compatibility, but
    the web side stores columns in lowercase. The forward path does
    not need this normalization because the YAML's ``legacy_column``
    names match the legacy CamelCase exactly and the web writes
    happen on the forward path.
    """
    out: dict[str, Any] = {}
    for col in mapping.columns:
        if col.legacy_column is None:
            continue
        out[col.legacy_column] = _case_insensitive_get(web_row, col.web_column)
    return out


def _compute_source_hash(row: dict[str, Any]) -> str:
    """SHA-256 hex of the canonical JSON of ``row``.

    Same contract as :func:`migration.apply._compute_source_hash`;
    the reverse audit log emits ``source_hash = SHA-256 of the
    web-side mapped payload`` and ``target_hash = SHA-256 of the
    legacy-side pre-update payload`` so the operator can trace the
    round-trip without trusting either side in isolation.
    """
    payload = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_web_select_sql(web_table: str, columns: tuple[str, ...]) -> str:
    """Build the ``SELECT cols FROM table`` for the reverse snapshot."""
    from migration.apply import _safe_table

    safe = _safe_table(web_table)
    cols = ", ".join(_safe_table(c) for c in columns) or "*"
    return f"SELECT {cols} FROM {safe}"


__all__ = [
    "_build_web_select_sql",
    "_case_insensitive_get",
    "_compute_source_hash",
    "_web_to_legacy_row",
]
