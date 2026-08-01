"""Service layer for the task engine (issue #7).

Owns SQL, validation, and mapping for the ``tarea`` table.

Public API:
  - enums: TipoTarea, EstadoTarea, PrioridadTarea, OrigenTarea
  - dataclass: Tarea
  - CRUD: crear_tarea, listar_tareas, obtener_tarea,
          actualizar_estado, asignar_tarea, cerrar_tarea

Validation contract:
  - Required: ``tipo``, ``origen`` (all others optional or defaulted)
  - ``estado`` transitions are validated against the EstadoTarea enum
  - ``responsable_id`` is nullable (unassigned tasks are allowed)
  - ``vencimiento_at`` is nullable (no deadline is valid)
  - ``vinculo_tipo`` / ``vinculo_id`` are nullable (link is optional)
  - ``metadata`` is nullable JSONB (extensible per task type)

All SQL is in ``queries.py`` (AGENTS.md §22 seam).
All log events go through ``log_safe`` (AGENTS.md §9).

Framework-agnostic: routes are thin HTTP glue; SQL, validation,
and mapping all live here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.data_access import SqlExecutor
from app.modules.tasks import queries as _queries

# --- enums ----------------------------------------------------------------


class TipoTarea(StrEnum):
    """Task type: manual or one of the automatic sub-types."""

    MANUAL = "manual"
    AUTOMATICA_VACUNA = "automatica_vacuna"
    AUTOMATICA_TRATAMIENTO = "automatica_tratamiento"
    AUTOMATICA_REVISION = "automatica_revision"
    AUTOMATICA_ESTERILIZACION = "automatica_esterilizacion"
    AUTOMATICA_MICROCHIP = "automatica_microchip"
    AUTOMATICA_DESPARASITACION = "automatica_desparasitacion"
    AUTOMATICA_SEGUIMIENTO_ACOGIDA = "automatica_seguimiento_acogida"
    AUTOMATICA_SEGUIMIENTO_POST_ADOPCION = "automatica_seguimiento_post_adopcion"
    AUTOMATICA_DOCUMENTACION = "automatica_documentacion"
    AUTOMATICA_ADMINISTRATIVA = "automatica_administrativa"


class EstadoTarea(StrEnum):
    """Lifecycle state of a task."""

    PENDIENTE = "pendiente"
    EN_PROGRESO = "en_progreso"
    COMPLETADA = "completada"
    CANCELADA = "cancelada"
    VENCIDA = "vencida"


class PrioridadTarea(StrEnum):
    """Business priority level."""

    BAJA = "baja"
    NORMAL = "normal"
    ALTA = "alta"
    URGENTE = "urgente"


class OrigenTarea(StrEnum):
    """What triggered the task creation."""

    DASHBOARD_MANUAL = "dashboard_manual"
    REGLA_SALUD = "regla_salud"
    REGLA_ACOGIDA = "regla_acogida"
    REGLA_ADOPCION = "regla_adopcion"
    REGLA_DOCUMENTACION = "regla_documentacion"
    REGLA_ADMINISTRATIVA = "regla_administrativa"


# --- dataclass ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Tarea:
    """A public row representation for ``tarea``."""

    id: str
    tipo: str
    origen: str
    prioridad: str
    estado: str
    responsable_id: str | None = None
    vencimiento_at: str | None = None
    vinculo_tipo: str | None = None
    vinculo_id: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


# --- exceptions -----------------------------------------------------------


class CerrarTareaError(ValueError):
    """Raised when closing a tarea in an invalid state."""

    def __init__(self, tarea_id: str, estado_actual: str) -> None:
        self.tarea_id = tarea_id
        self.estado_actual = estado_actual
        super().__init__(
            f"Cannot close tarea {tarea_id}: estado is '{estado_actual}', "
            "expected one of 'pendiente', 'en_progreso'."
        )


# --- helpers --------------------------------------------------------------


def _row_to_tarea(row: dict) -> Tarea:
    """Map a DB row dict to a Tarea dataclass."""
    metadata_raw = row.get("metadata")
    if isinstance(metadata_raw, str):
        metadata = json.loads(metadata_raw) if metadata_raw else None
    else:
        metadata = metadata_raw
    return Tarea(
        id=str(row["id"]),
        tipo=str(row["tipo"]),
        origen=str(row["origen"]),
        prioridad=str(row["prioridad"]),
        estado=str(row["estado"]),
        responsable_id=str(row["responsable_id"]) if row.get("responsable_id") else None,
        vencimiento_at=str(row["vencimiento_at"]) if row.get("vencimiento_at") else None,
        vinculo_tipo=str(row["vinculo_tipo"]) if row.get("vinculo_tipo") else None,
        vinculo_id=str(row["vinculo_id"]) if row.get("vinculo_id") else None,
        metadata=metadata,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
        updated_at=str(row["updated_at"]) if row.get("updated_at") else None,
    )


def _coerce_estado(value: str) -> EstadoTarea:
    """Coerce a string to EstadoTarea, raise ValueError on invalid."""
    try:
        return EstadoTarea(value)
    except ValueError:
        raise ValueError(
            f"estado must be one of {[m.value for m in EstadoTarea]}, "
            f"got: {value!r}"
        ) from None


# --- public API -----------------------------------------------------------


def crear_tarea(  # noqa: PLR0913  # service facade; 8 args mirror the task creation domain model
    client: SqlExecutor,
    *,
    tipo: str,
    origen: str,
    prioridad: str = "normal",
    responsable_id: str | None = None,
    vencimiento_at: str | None = None,
    vinculo_tipo: str | None = None,
    vinculo_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create a new tarea and return its UUID.

    Raises ValueError if tipo or origen are not valid enum members.
    """
    # Validate enums
    try:
        TipoTarea(tipo)
    except ValueError:
        raise ValueError(
            f"tipo must be one of {[m.value for m in TipoTarea]}, got: {tipo!r}"
        ) from None
    try:
        OrigenTarea(origen)
    except ValueError:
        raise ValueError(
            f"origen must be one of {[m.value for m in OrigenTarea]}, got: {origen!r}"
        ) from None
    try:
        PrioridadTarea(prioridad)
    except ValueError:
        raise ValueError(
            f"prioridad must be one of {[m.value for m in PrioridadTarea]}, "
            f"got: {prioridad!r}"
        ) from None

    sql, params = _queries.build_insert_tarea(
        tipo=tipo,
        origen=origen,
        prioridad=prioridad,
        responsable_id=responsable_id,
        vencimiento_at=vencimiento_at,
        vinculo_tipo=vinculo_tipo,
        vinculo_id=vinculo_id,
        metadata=metadata,
    )
    rows = client.execute_sql(sql, params)
    return str(rows[0]["id"])


def listar_tareas(  # noqa: PLR0913  # service facade; 7 args mirror the task list filter surface
    client: SqlExecutor,
    *,
    estado: str | None = None,
    responsable_id: str | None = None,
    vinculo_tipo: str | None = None,
    vinculo_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Tarea]:
    """List tareas with optional filters.

    Returns a list of Tarea objects sorted by priority bucket, then
    vencimiento_at, then created_at desc.
    """
    if estado is not None:
        _coerce_estado(estado)  # validate filter value

    sql, params = _queries.build_list_tareas(
        estado=estado,
        responsable_id=responsable_id,
        vinculo_tipo=vinculo_tipo,
        vinculo_id=vinculo_id,
        limit=limit,
        offset=offset,
    )
    rows = client.execute_sql(sql, params)
    return [_row_to_tarea(row) for row in rows]


def obtener_tarea(client: SqlExecutor, *, tarea_id: str) -> Tarea | None:
    """Get a single tarea by id. Returns None if not found."""
    sql, params = _queries.build_get_tarea(tarea_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        return None
    return _row_to_tarea(rows[0])


def actualizar_estado(
    client: SqlExecutor,
    *,
    tarea_id: str,
    nuevo_estado: str,
) -> Tarea:
    """Transition a tarea to a new estado.

    Raises ValueError if nuevo_estado is not a valid EstadoTarea.
    Raises ValueError if the tarea does not exist.
    """
    nuevo = _coerce_estado(nuevo_estado)

    sql, params = _queries.build_update_estado(tarea_id, nuevo.value)
    rows = client.execute_sql(sql, params)
    if not rows:
        raise ValueError(f"Tarea {tarea_id} not found")
    return _row_to_tarea(rows[0])


def asignar_tarea(
    client: SqlExecutor,
    *,
    tarea_id: str,
    responsable_id: str | None,
) -> Tarea:
    """Assign a tarea to a responsable (or unassign if responsable_id is None).

    Raises ValueError if the tarea does not exist.
    """
    sql, params = _queries.build_update_responsable(tarea_id, responsable_id)
    rows = client.execute_sql(sql, params)
    if not rows:
        raise ValueError(f"Tarea {tarea_id} not found")
    return _row_to_tarea(rows[0])


def cerrar_tarea(
    client: SqlExecutor,
    *,
    tarea_id: str,
    comentario: str | None = None,
) -> Tarea:
    """Close a tarea by setting its estado to 'completada'.

    Valid from states: 'pendiente' or 'en_progreso'.
    Raises CerrarTareaError if called from an invalid state.
    Raises ValueError if the tarea does not exist.
    """
    # First get current state
    existente = obtener_tarea(client, tarea_id=tarea_id)
    if existente is None:
        raise ValueError(f"Tarea {tarea_id} not found")
    if existente.estado not in (EstadoTarea.PENDIENTE.value, EstadoTarea.EN_PROGRESO.value):
        raise CerrarTareaError(tarea_id, existente.estado)

    # Update estado
    sql, params = _queries.build_update_estado(
        tarea_id, EstadoTarea.COMPLETADA.value
    )
    rows = client.execute_sql(sql, params)
    if not rows:
        raise ValueError(f"Tarea {tarea_id} not found")

    # Optionally store the closing comment in metadata.
    # If the metadata update returns no rows (e.g. no match in fake),
    # fall back to the estado-update result.
    if comentario:
        sql2, params2 = _queries.build_update_metadata(tarea_id, comentario)
        metadata_rows = client.execute_sql(sql2, params2)
        if metadata_rows:
            return _row_to_tarea(metadata_rows[0])

    return _row_to_tarea(rows[0])
