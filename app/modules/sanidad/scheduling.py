"""Periodic task scheduling for health actuations (HEALTH-05, #54).

Wired from ``sanidad/service.py`` after each ``create_actuacion_sanitaria``.
One-shot tests (``periodicidad_meses IS NULL``) produce no task.
Failures are non-fatal: the operator gets the actuation confirmation even
if the scheduling step fails; errors are logged for investigation.

Module boundary: this file owns the wiring between the periodicity engine
(``periodicity.py``) and the task engine (``app.modules.tasks``).
The pure scheduling logic (rule lookup, next-date computation, task-param
building) lives in ``periodicity.py``; this module handles the SQL reads,
the ``tareas_service.crear_tarea`` call, and the error-logging wrapper.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.data_access import SqlExecutor
    from app.modules.sanidad.service import ActuacionSanitaria


def schedule_periodic_task(
    client: SqlExecutor,
    actuacion: ActuacionSanitaria,
    catalogos_periodicidad: list[dict[str, Any]],
) -> None:
    """Create a linked ``tarea`` for the next occurrence of a recurring health test.

    Called from ``sanidad/service.py`` after each ``create_actuacion_sanitaria``.
    Short-circuits when ``tipo_actuacion_id`` is ``None`` (no rule to look up).

    Failures in task creation are non-fatal (logged only); the actuation was
    already committed and the operator must not be blocked by a scheduling error.
    """
    if not actuacion.tipo_actuacion_id:
        return

    from app.core.logging import log_safe  # lazy-import: schedule module loaded at module level from service.py
    from app.modules.sanidad.periodicity import (  # lazy-import: avoids circular dep (periodicity.py is framework-agnostic)
        find_periodicity_rule,
        generate_next_tarea,
    )

    # --- fetch tipo_actuacion.codigo ----------------------------------------
    tipo_rows = client.execute_sql(
        _GET_TIPO_CODIGO_SQL, [actuacion.tipo_actuacion_id]
    )
    if not tipo_rows:
        return
    codigo = str(tipo_rows[0].get("codigo") or "")

    # --- fetch animal.especie -----------------------------------------------
    especie_rows = client.execute_sql(
        _GET_ANIMAL_ESPECIE_SQL, [actuacion.animal_id]
    )
    if not especie_rows:
        return
    especie_raw = especie_rows[0].get("especie") or ""
    especie: str | None = especie_raw.upper() if especie_raw else None

    # --- find rule ----------------------------------------------------------
    rule = find_periodicity_rule(catalogos_periodicidad, codigo, especie)
    if rule is None or not rule.is_recurring():
        return

    # --- validate + compute next due date -----------------------------------
    try:
        fecha_date = date.fromisoformat(actuacion.fecha)
    except Exception:
        log_safe(
            "sanidad.periodicity.compute_error",
            actuacion_id=actuacion.id,
            error=str(Exception),
        )
        return

    try:
        rule.next_due_date(fecha_date)  # validate; raises on bad rule
    except Exception:
        log_safe(
            "sanidad.periodicity.compute_error",
            actuacion_id=actuacion.id,
            error=str(Exception),
        )
        return

    # --- build task params -------------------------------------------------
    task_params = generate_next_tarea(
        last_actuacion_date=fecha_date,
        periodicidad_rule=rule,
        animal_id=actuacion.animal_id,
        actuacion_id=actuacion.id,
    )
    if task_params is None:
        return

    # --- create tarea (non-fatal) ------------------------------------------
    try:
        from app.modules.tasks import crear_tarea  # lazy-import: avoids circular dep
        crear_tarea(
            client=client,
            tipo=task_params["tipo"],
            origen=task_params["origen"],
            prioridad=task_params["prioridad"],
            vencimiento_at=task_params["vencimiento_at"],
            vinculo_tipo=task_params["vinculo_tipo"],
            vinculo_id=task_params["vinculo_id"],
            metadata=task_params["metadata"],
        )
        log_safe(
            "sanidad.periodicity.task_created",
            tarea_tipo=task_params["tipo"],
            actuacion_id=actuacion.id,
            animal_id=actuacion.animal_id,
            next_due_date=task_params["vencimiento_at"],
        )
    except Exception:
        log_safe(
            "sanidad.periodicity.task_create_error",
            actuacion_id=actuacion.id,
            error=str(Exception),
        )


# --- SQL constants (also used by service.py for the inline queries) ---------


_GET_TIPO_CODIGO_SQL = (
    "SELECT codigo FROM catalogos_pruebas WHERE id = $1"
)

_GET_ANIMAL_ESPECIE_SQL = (
    "SELECT especie FROM animales WHERE id = $1 AND activo = true"
)
