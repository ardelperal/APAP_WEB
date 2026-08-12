"""``can_delete_animal`` use case (LIFECYCLE-03 PR-C).

Mirrors the legacy ``AnimalBorrable`` contract documented at
``docs/legacy-lifecycle-transition-rules.md:108-113`` where the only
"deletable" animal is one with no rows in any of ``entradas`` /
``acogidas`` / ``adopciones`` / ``actuaciones_sanitarias`` /
``terapias``. The use case returns a structured
:class:`CanDeleteResult` carrying the offending table name so the
caller (route handler, future deletion flow) can produce a precise
``409 Conflict`` response with the diagnostic.

When ``actuaciones_sanitarias`` or ``terapias`` does not exist in the
deployment (some environments do not have the health / therapy
modules bootstrap-installed), the use case returns
``reason="sanidad_table_missing"`` or ``reason="terapias_table_missing"``
rather than raising — the caller treats missing tables as
"non-deletable" conservatively (no animal can be deleted until the
table is bootstrapped).

The use case takes the ``SqlExecutor`` Protocol (AGENTS.md §31) and
does NOT import ``InsForgeClient``. The lifecycle slice does not own
a dedicated adapter for read-only checks; issuing 5 ``COUNT(*)``
queries is small enough that the application layer owns its own SQL
strings directly. The pattern matches ``close_all_on_death`` — the
lifecycle use cases share a single seam for SQL that does not need
the cascade projection shape.

LIFECYCLE-03 (issue #33) PR-C work-unit C6.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.core.data_access import SqlExecutor

#: Reason constants for ``CanDeleteResult``. The set is closed
#: (AGENTS.md §4 — one source of truth per domain concept); adding a
#: new table means adding a member here AND extending ``_TABLE_CHECKS``.
REASON_ENTRADA_ROW: Final[str] = "entrada_row"
REASON_ACOGIDA_ROW: Final[str] = "acogida_row"
REASON_ADOPCION_ROW: Final[str] = "adopcion_row"
REASON_SANIDAD_ROW: Final[str] = "sanidad_row"
REASON_SANIDAD_TABLE_MISSING: Final[str] = "sanidad_table_missing"
REASON_TERAPIA_ROW: Final[str] = "terapia_row"
REASON_TERAPIAS_TABLE_MISSING: Final[str] = "terapias_table_missing"


#: The table check schedule. Order matters — the first non-empty
#: table's reason wins. Lifecycle tables come first (the most common
#: reason an animal is not deletable is that it has an active
#: placement); health tables come second.
_TABLE_CHECKS: Final[tuple[tuple[str, str, str], ...]] = (
    ("entradas", "SELECT COUNT(*) AS count FROM entradas WHERE animal_id = $1", REASON_ENTRADA_ROW),
    ("acogidas", "SELECT COUNT(*) AS count FROM acogidas WHERE animal_id = $1", REASON_ACOGIDA_ROW),
    ("adopciones", "SELECT COUNT(*) AS count FROM adopciones WHERE animal_id = $1", REASON_ADOPCION_ROW),
    (
        "actuaciones_sanitarias",
        "SELECT COUNT(*) AS count FROM actuaciones_sanitarias WHERE animal_id = $1",
        REASON_SANIDAD_ROW,
    ),
    (
        "terapias",
        "SELECT COUNT(*) AS count FROM terapias WHERE animal_id = $1",
        REASON_TERAPIA_ROW,
    ),
)


@dataclass(frozen=True, slots=True)
class CanDeleteResult:
    """Structured outcome of :func:`can_delete_animal`.

    ``can_delete`` is True only when every inspected table returns
    zero rows. ``reason`` is ``None`` when ``can_delete`` is True,
    or one of the ``REASON_*`` constants otherwise. The reason
    names the **first** non-empty table in
    :data:`_TABLE_CHECKS` order; subsequent tables are not queried
    once a reason is determined (the result is the union of "any
    non-empty" — the first non-empty wins the audit log).
    """

    can_delete: bool
    reason: str | None = None


#: Substrings of the relation-not-found error message that indicate a
#: missing table. The check uses ``in`` so it tolerates the variant
#: phrasings across the Python ``psycopg`` / ``asyncpg`` / InsForge
#: error surfaces ("relation ... does not exist",
#: "no such table", etc.).
_MISSING_TABLE_ERROR_MARKERS: Final[tuple[str, ...]] = (
    "does not exist",
    "no such table",
    "undefined_table",
)


def _is_missing_table_error(exc: BaseException) -> bool:
    """True when ``exc`` is a relation-not-found SQL error."""
    message = str(exc).lower()
    return any(marker in message for marker in _MISSING_TABLE_ERROR_MARKERS)


def can_delete_animal(executor: SqlExecutor, animal_id: str) -> CanDeleteResult:
    """Return :class:`CanDeleteResult` for the animal.

    Parameters
    ----------
    executor
        The ``SqlExecutor`` for the live DB session (AGENTS.md §31).
    animal_id
        The animal whose deletability is being checked.

    Returns
    -------
    CanDeleteResult
        ``(can_delete=True, reason=None)`` when every one of the 5
        inspected tables returns zero rows; ``(can_delete=False,
        reason=<table>_row)`` when the first non-empty table is a
        data row; ``(can_delete=False, reason=<table>_table_missing)``
        when the first errored table is missing.

    Notes
    -----
    The use case is intentionally short-circuit: once a non-empty
    table is found the remaining tables are not queried. The first
    non-empty reason is the most useful diagnostic for the operator
    (the most common reason is the lifecycle tables — an animal
    with active records is rarely also blocked by sanidad / terapias).
    """
    for table, sql, row_reason in _TABLE_CHECKS:
        try:
            rows = executor.execute_sql(sql, [animal_id])
        except Exception as exc:  # noqa: BLE001 — transport-agnostic guard
            if not _is_missing_table_error(exc):
                raise
            if table == "actuaciones_sanitarias":
                return CanDeleteResult(can_delete=False, reason=REASON_SANIDAD_TABLE_MISSING)
            if table == "terapias":
                return CanDeleteResult(can_delete=False, reason=REASON_TERAPIAS_TABLE_MISSING)
            # Other tables (entradas / acogidas / adopciones) are part
            # of the bootstrap; a missing one is a config error, not a
            # deletability verdict. Re-raise so the operator sees it.
            raise
        if rows and int(rows[0].get("count", 0) or 0) > 0:
            return CanDeleteResult(can_delete=False, reason=row_reason)

    return CanDeleteResult(can_delete=True, reason=None)


__all__ = [
    "CanDeleteResult",
    "REASON_ACOGIDA_ROW",
    "REASON_ADOPCION_ROW",
    "REASON_ENTRADA_ROW",
    "REASON_SANIDAD_ROW",
    "REASON_SANIDAD_TABLE_MISSING",
    "REASON_TERAPIA_ROW",
    "REASON_TERAPIAS_TABLE_MISSING",
    "can_delete_animal",
]
