"""Service operations for material assignments to foster stays.

Per AGENTS.md §22, the SQL/service separation seam: SQL strings and
parameter shaping live in ``app.modules.materiales.queries``; this
module imports those builders, applies domain validation, and talks
to the client. The seam is testable: the shape of the SQL is asserted
in ``tests/test_materiales_queries.py`` without spinning up transport.
"""

from __future__ import annotations

from app.core.data_access import SqlExecutor
from app.core.insforge import InsForgeError
from app.core.logging import log_safe
from app.modules.materiales import queries
from app.modules.materiales.service import (
    EstanciaMaterial,
    MaterialConflictError,
    _is_unique_violation,
    _row_to_estancia_material,
    _validate_estancia_open_and_active,
    _validate_material_active,
)


def assign_material_to_estancia(
    client: SqlExecutor,
    estancia_id: str,
    material_id: str,
    cantidad: int = 1,
    notas: str | None = None,
) -> EstanciaMaterial:
    """Insert a junction row tying ``material_id`` to ``estancia_id``.

    Validates BEFORE the INSERT:

    1. ``estancia_id`` must point at an active estancia sin
       ``fecha_final`` (Q5 — closed or soft-deleted stays are
       rejected).
    2. ``material_id`` must point at an active material (Scenario 8 —
       soft-deleted materials are rejected).
    3. ``cantidad`` is integer > 0 (defense in depth on top of the
       DB CHECK constraint — enforced by the
       ``queries.build_junction_insert`` builder).

    The partial unique index
    ``estancia_materiales_active_unique`` on
    ``(estancia_id, material_id) WHERE activo = true`` catches a
    duplicate active assignment and surfaces it as PostgreSQL 23505;
    the service translates that to ``MaterialConflictError`` so the
    route layer can map it to HTTP 409 (Scenario 4 in spec #15894).
    """
    # Validation runs BEFORE the INSERT so we never write a junction
    # row with invalid FKs.
    _validate_estancia_open_and_active(client, estancia_id)
    _validate_material_active(client, material_id)

    sql, write_params = queries.build_junction_insert(
        estancia_id, material_id, cantidad, notas
    )
    try:
        rows = client.execute_sql(sql, write_params)
    except InsForgeError as exc:
        if _is_unique_violation(exc):
            raise MaterialConflictError(
                "ese material ya esta asignado a esta estancia"
            ) from exc
        raise
    junction = _row_to_estancia_material(rows[0])
    log_safe(
        "materiales.assigned",
        estancia_id=estancia_id,
        material_id=material_id,
        cantidad=cantidad,
    )
    return junction


def list_materials_for_estancia(
    client: SqlExecutor,
    estancia_id: str,
    activos_solo: bool = True,
) -> list[EstanciaMaterial]:
    """Return junction rows for ``estancia_id`` ordered by fecha_alta DESC.

    ``activos_solo=True`` (the default) returns only active rows — the
    operator's per-stay material list (Scenario 5 in spec #15894).
    ``activos_solo=False`` returns every row including soft-deleted —
    the admin / audit view (Q-T1, deferred to Fase 6c).
    """
    sql, params = queries.build_junction_list_for_estancia(
        estancia_id, activos_solo
    )
    rows = client.execute_sql(sql, params)
    return [_row_to_estancia_material(row) for row in rows]


def remove_material_from_estancia(
    client: SqlExecutor, junction_id: str
) -> bool:
    """Atomically soft-delete a single junction row.

    Returns ``True`` if the row was active and was deactivated.
    Returns ``False`` if the row does not exist OR was already inactive
    (idempotent — same shape as ``deactivate_material`` on the catalog).

    Scenario 11 / AC8 in spec #15894 — a soft-delete preserves the
    historical row in DB (activo=false) for future auditability. No
    admin view yet (Fase 6c).
    """
    sql, params = queries.build_junction_deactivate(junction_id)
    rows = client.execute_sql(sql, params)
    removed = bool(rows)
    if removed:
        log_safe(
            "materiales.unassigned",
            junction_id=junction_id,
        )
    return removed


__all__ = [
    "EstanciaMaterial",
    "assign_material_to_estancia",
    "list_materials_for_estancia",
    "remove_material_from_estancia",
]
