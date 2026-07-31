"""Task engine — public API for the ``tareas`` module."""

from app.core.tasks.rules import (
    TASK_RULES,
    TareaDraft,
    rule_esterilizacion_pendiente,
    rule_seguimiento_post_adopcion,
    rule_vacuna_vencimiento,
)
from app.modules.tasks.service import (
    CerrarTareaError,
    EstadoTarea,
    OrigenTarea,
    PrioridadTarea,
    Tarea,
    TipoTarea,
    actualizar_estado,
    asignar_tarea,
    cerrar_tarea,
    crear_tarea,
    listar_tareas,
    obtener_tarea,
)

__all__ = [
    "Tarea",
    "TipoTarea",
    "EstadoTarea",
    "PrioridadTarea",
    "OrigenTarea",
    "CerrarTareaError",
    "TareaDraft",
    "TASK_RULES",
    "rule_vacuna_vencimiento",
    "rule_seguimiento_post_adopcion",
    "rule_esterilizacion_pendiente",
    "crear_tarea",
    "listar_tareas",
    "obtener_tarea",
    "actualizar_estado",
    "asignar_tarea",
    "cerrar_tarea",
]
