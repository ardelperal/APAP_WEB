"""Adopciones module (ADOPT-01, #47) and ADOPT-03 (#49).

Exports the service + the router so the rest of the app can do
``from app.modules.adopciones import service, router``.
"""

from app.modules.adopciones.routes import router
from app.modules.adopciones.service import (
    Adopcion,
    AdopcionConflictError,
    SeguimientoAction,
    SeguimientoEstado,
    SeguimientoTransitionResult,
    transition_seguimiento,
)

__all__ = [
    "router",
    "Adopcion",
    "AdopcionConflictError",
    "SeguimientoAction",
    "SeguimientoEstado",
    "SeguimientoTransitionResult",
    "transition_seguimiento",
]
