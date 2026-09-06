"""Service layer for HEALTH-04 salud (CRUD).

Owns SQL, validation, FK checks, mapping, and soft-delete for the
``terapias`` and ``recomendaciones`` tables (HEALTH-04, issue #53).

Validation contract:

- ``terapias`` required fields: ``animal_id``, ``voluntario_id``, ``fecha``.
- ``animal_id`` MUST reference an active ``animales`` row.
- ``voluntario_id`` MUST reference an active ``voluntarios`` row (VOL-05).
- ``recomendaciones`` required fields: ``terapia_id``, ``fecha``, ``texto``.
- ``terapia_id`` MUST reference an active ``terapias`` row.

Delete restriction (spec §"Restricción de borrado de terapia"):
    A terapia with any ``activo=true AND completada=false`` recomendacion
    CANNOT be deleted. The ``DELETE_TERAPIA`` CTE pre-checks this and
    returns 0 rows when the constraint is violated; the service raises
    ``TerapiaHasPendingRecomendaciones``.

CRITICAL-1 (TOCTOU-safe writes): create / update run validation + write
in a single CTE so PostgreSQL's statement-level snapshot eliminates the
window between the FK SELECTs and the INSERT / UPDATE.

Framework-agnostic: routes are thin HTTP glue; SQL, validation, and
mapping all live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.data_access import SqlExecutor
from app.core.forms import required_text
from app.core.logging import log_safe
from app.modules.salud import queries as salud_queries


class TerapiaHasPendingRecomendaciones(ValueError):
    """Raised when deleting a terapia that still has active recommendations."""


class TerapiaNotFoundError(ValueError):
    """Raised when a terapia does not exist or is already soft-deleted."""


class RecomendacionNotFoundError(ValueError):
    """Raised when a recomendacion does not exist or is already soft-deleted."""


# --- domain models ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Terapia:
    """Public representation of a ``terapias`` row."""

    id: str
    animal_id: str
    voluntario_id: str
    fecha: str
    descripcion: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    activo: bool = True


@dataclass(frozen=True, slots=True)
class Recomendacion:
    """Public representation of a ``recomendaciones`` row."""

    id: str
    terapia_id: str
    fecha: str
    texto: str
    completada: bool = False
    created_at: str | None = None
    activo: bool = True


# --- row mappers -----------------------------------------------------------


def _row_to_terapia(row: dict[str, Any]) -> Terapia:
    return Terapia(
        id=str(row["id"]),
        animal_id=str(row["animal_id"]),
        voluntario_id=str(row["voluntario_id"]),
        fecha=str(row["fecha"]),
        descripcion=row.get("descripcion"),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
        activo=bool(row.get("activo", True)),
    )


def _row_to_recomendacion(row: dict[str, Any]) -> Recomendacion:
    return Recomendacion(
        id=str(row["id"]),
        terapia_id=str(row["terapia_id"]),
        fecha=str(row["fecha"]),
        texto=str(row["texto"]),
        completada=bool(row.get("completada", False)),
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        activo=bool(row.get("activo", True)),
    )


def _raise_terapia_fk_error(
    client: SqlExecutor, params: dict[str, Any]
) -> None:
    """Disambiguate a 0-row terapia CTE result.

    Called ONLY after the atomic CTE returned 0 rows. Re-runs targeted
    SELECTs to identify which check failed and raise a specific
    ``ValueError`` for the operator UX.
    """
    animal_id = required_text(params, "animal_id")
    vol_id = required_text(params, "voluntario_id")

    animal_rows = client.execute_sql(
        "SELECT id, activo FROM animales WHERE id = $1",
        [animal_id],
    )
    if not animal_rows:
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (no encontrado: {animal_id})"
        )
    if not animal_rows[0].get("activo", False):
        raise ValueError(
            f"animal_id debe apuntar a un animal activo (inactivo: {animal_id})"
        )

    vol_rows = client.execute_sql(
        "SELECT id, activo FROM voluntarios WHERE id = $1",
        [vol_id],
    )
    if not vol_rows:
        raise ValueError(
            f"voluntario_id debe apuntar a un voluntario activo (no encontrado: {vol_id})"
        )
    if not vol_rows[0].get("activo", False):
        raise ValueError(
            f"voluntario_id debe apuntar a un voluntario activo (inactivo: {vol_id})"
        )

    # Lifecycle gate (issue #46 follow-up): the CTE rejected the animal
    # not because of an FK or active-flag issue (those branches above
    # returned), but because ``animal_current_state.current_state`` is
    # one of the blocked states (``Incoherente`` or any ``Fallecido (*)``
    # variant). Surface the Spanish lifecycle error copy so the
    # operator UI can render the actionable message.
    lifecycle_rows = client.execute_sql(
        "SELECT current_state FROM animal_current_state WHERE animal_id = $1",
        [animal_id],
    )
    if lifecycle_rows:
        current_state = lifecycle_rows[0].get("current_state") or ""
        if current_state == "Incoherente" or current_state.startswith("Fallecido"):
            raise ValueError(
                f"animal_id en estado {current_state} — "
                "no se puede registrar terapia para animales "
                "fallecidos o incoherentes"
            )

    raise ValueError(
        "FK validation failed (animal_id, voluntario_id) — none matched"
    )


def _raise_recomendacion_fk_error(
    client: SqlExecutor, terapia_id: str
) -> None:
    """Disambiguate a 0-row recomendacion CTE result."""
    terapia_rows = client.execute_sql(
        "SELECT id, activo FROM terapias WHERE id = $1",
        [terapia_id],
    )
    if not terapia_rows:
        raise ValueError(
            f"terapia_id no existe (no encontrada: {terapia_id})"
        )
    if not terapia_rows[0].get("activo", False):
        raise ValueError(
            f"terapia_id no está activa (ya eliminada: {terapia_id})"
        )
    raise ValueError(
        f"recomendacion FK validation failed for terapia_id: {terapia_id}"
    )


# --- terapia public API ----------------------------------------------------


def create_terapia(
    client: SqlExecutor,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Terapia:
    """Insert a new ``terapias`` row in one CTE statement.

    The CTE bundles the FK checks (animal activo, voluntario activo per
    VOL-05) with the INSERT so PostgreSQL evaluates them under a single
    statement snapshot — no window for concurrent deactivation between
    the SELECT and the write (CRITICAL-1).

    On 0 rows returned by the CTE, :func:`_raise_terapia_fk_error` runs
    targeted SELECTs to identify which check failed.
    """
    # Validate required fields before DB round-trip
    required_text(params, "animal_id")
    required_text(params, "voluntario_id")
    required_text(params, "fecha")

    sql, sql_params = salud_queries.build_create_terapia(params)
    rows = client.execute_sql(sql, sql_params)
    if not rows:
        _raise_terapia_fk_error(client, params)

    terapia = _row_to_terapia(rows[0])
    log_safe(
        "therapy.created",
        terapia_id=terapia.id,
        animal_id=terapia.animal_id,
        fecha=terapia.fecha,
        actor_user_id=actor_user_id,
    )
    return terapia


def list_terapias(
    client: SqlExecutor,
    *,
    animal_id: str | None = None,
) -> list[Terapia]:
    """Return active ``terapias`` rows, most recent first.

    When ``animal_id`` is provided, filters to that animal.
    Otherwise returns the global list (LIMIT 100).
    """
    sql, params = salud_queries.build_list_terapias(animal_id=animal_id)
    rows = client.execute_sql(sql, params)
    return [_row_to_terapia(row) for row in rows]


def get_terapia_by_id(
    client: SqlExecutor, terapia_id: str
) -> Terapia | None:
    """Return one ``terapias`` row by id (active or inactive), or ``None``."""
    sql, params = salud_queries.build_get_terapia(terapia_id)
    rows = client.execute_sql(sql, params)
    return _row_to_terapia(rows[0]) if rows else None


def update_terapia(
    client: SqlExecutor,
    terapia_id: str,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Terapia | None:
    """Update an existing ``terapias`` row in one CTE statement.

    Same single-snapshot CTE pattern as :func:`create_terapia` (FK
    active checks + UPDATE atomic). Returns ``None`` when the id does
    not exist. On 0 rows due to a failed FK check,
    :func:`_raise_terapia_fk_error` raises a specific ``ValueError``.
    """
    # Validate required fields
    required_text(params, "animal_id")
    required_text(params, "voluntario_id")
    required_text(params, "fecha")

    sql, sql_params = salud_queries.build_update_terapia(terapia_id, params)
    rows = client.execute_sql(sql, sql_params)
    if not rows:
        # Either id is missing or a FK check failed
        if get_terapia_by_id(client, terapia_id) is None:
            return None
        _raise_terapia_fk_error(client, params)

    terapia = _row_to_terapia(rows[0])
    log_safe(
        "therapy.updated",
        terapia_id=terapia.id,
        animal_id=terapia.animal_id,
        fecha=terapia.fecha,
        actor_user_id=actor_user_id,
    )
    return terapia


def delete_terapia(
    client: SqlExecutor,
    terapia_id: str,
    *,
    actor_user_id: str | None = None,
) -> bool:
    """Atomically soft-delete a ``terapias`` row.

    Returns ``True`` when the row was active and was deactivated.
    Returns ``False`` when the row does not exist, is already
    inactive, or has pending recommendations (completada=false).

    The ``WHERE`` clause in the CTE pre-checks that no active
    incomplete recommendations exist; if any do, the UPDATE does not
    execute and 0 rows are returned, triggering the
    ``TerapiaHasPendingRecomendaciones`` error.
    """
    sql, params = salud_queries.build_delete_terapia(terapia_id)
    rows = client.execute_sql(sql, params)
    if rows:
        log_safe(
            "therapy.deleted",
            terapia_id=terapia_id,
            actor_user_id=actor_user_id,
        )
        return True

    # Distinguish "not found" from "has pending recommendations"
    # by checking if the terapia exists at all
    terapia = get_terapia_by_id(client, terapia_id)
    if terapia is None:
        return False  # Already deleted or never existed

    # terapia exists and is active — must be the pending-recommendations check
    # that blocked the delete. Verify by counting pending.
    pending = list_recomendaciones(client, terapia_id)
    has_pending = any(not r.completada and r.activo for r in pending)
    if has_pending:
        raise TerapiaHasPendingRecomendaciones(
            f"terapia {terapia_id} tiene recomendaciones pendientes"
        )
    return False


# --- recomendacion public API -----------------------------------------------


def create_recomendacion(
    client: SqlExecutor,
    params: dict[str, Any],
    *,
    actor_user_id: str | None = None,
) -> Recomendacion:
    """Insert a new ``recomendaciones`` row in one CTE statement.

    The CTE checks that ``terapia_id`` references an active ``terapias``
    row. On 0 rows returned, :func:`_raise_recomendacion_fk_error` raises
    a specific ``ValueError``.
    """
    required_text(params, "terapia_id")
    required_text(params, "fecha")
    required_text(params, "texto")

    sql, sql_params = salud_queries.build_create_recomendacion(params)
    rows = client.execute_sql(sql, sql_params)
    if not rows:
        _raise_recomendacion_fk_error(client, params["terapia_id"])

    recomendacion = _row_to_recomendacion(rows[0])
    log_safe(
        "recomendacion.created",
        recomendacion_id=recomendacion.id,
        terapia_id=recomendacion.terapia_id,
        actor_user_id=actor_user_id,
    )
    return recomendacion


def list_recomendaciones(
    client: SqlExecutor, terapia_id: str
) -> list[Recomendacion]:
    """Return active ``recomendaciones`` for ``terapia_id``."""
    sql, params = salud_queries.build_list_recomendaciones_by_terapia(terapia_id)
    rows = client.execute_sql(sql, params)
    return [_row_to_recomendacion(row) for row in rows]


def get_recomendacion_by_id(
    client: SqlExecutor, recomendacion_id: str
) -> Recomendacion | None:
    """Return one ``recomendaciones`` row by id, or ``None``."""
    sql, params = salud_queries.build_get_recomendacion(recomendacion_id)
    rows = client.execute_sql(sql, params)
    return _row_to_recomendacion(rows[0]) if rows else None


def complete_recomendacion(
    client: SqlExecutor,
    recomendacion_id: str,
    *,
    actor_user_id: str | None = None,
) -> Recomendacion:
    """Mark a ``recomendaciones`` row as completed (completada=true).

    Returns the updated row. Raises ``RecomendacionNotFoundError`` when
    the row does not exist or is already soft-deleted.
    """
    sql, params = salud_queries.build_complete_recomendacion(recomendacion_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        raise RecomendacionNotFoundError(
            f"recomendacion not found or already completed: {recomendacion_id}"
        )
    recomendacion = _row_to_recomendacion(rows[0])
    log_safe(
        "recomendacion.completed",
        recomendacion_id=recomendacion.id,
        terapia_id=recomendacion.terapia_id,
        actor_user_id=actor_user_id,
    )
    return recomendacion


def delete_recomendacion(
    client: SqlExecutor,
    recomendacion_id: str,
    *,
    actor_user_id: str | None = None,
) -> bool:
    """Soft-delete a ``recomendaciones`` row.

    Returns ``True`` when deleted; ``False`` when not found or already
    inactive.
    """
    sql, params = salud_queries.build_delete_recomendacion(recomendacion_id)
    rows = client.execute_sql(sql, params)
    deleted = bool(rows)
    if deleted:
        log_safe(
            "recomendacion.deleted",
            recomendacion_id=recomendacion_id,
            actor_user_id=actor_user_id,
        )
    return deleted
