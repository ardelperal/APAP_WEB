"""Adopciones module (ADOPT-01, #47).

Exports the service + the router so the rest of the app can do
``from app.modules.adopciones import service, router``.
"""

from app.modules.adopciones.routes import router
from app.modules.adopciones.service import (
    Adopcion,
    AdopcionConflictError,
)

__all__ = [
    "router",
    "Adopcion",
    "AdopcionConflictError",
]
