"""Casas de Acogida module (FOSTER-01, #43).

Exports the service + the router so the rest of the app can do
``from app.modules.foster import service, router``.
"""

from app.modules.foster.routes import router
from app.modules.foster.service import (
    VALID_COCHE_VALUES,
    VALID_ESPECIE_VALUES,
    CasaAcogida,
    CasaAcogidaConflictError,
)

__all__ = [
    "router",
    "CasaAcogida",
    "CasaAcogidaConflictError",
    "VALID_COCHE_VALUES",
    "VALID_ESPECIE_VALUES",
]
