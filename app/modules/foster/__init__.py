"""Casas de Acogida module (FOSTER-01, #43 + FOSTER-03, #45).

Exports the service + the router + the assignment service so the rest
of the app can do ``from app.modules.foster import service, router,
assignment_service``.
"""

from app.modules.foster import assignment as assignment_service
from app.modules.foster.assignment import (
    AssignmentDecision,
    FosterCapacityOverride,
)
from app.modules.foster.routes import router
from app.modules.foster.service import (
    VALID_COCHE_VALUES,
    VALID_ESPECIE_VALUES,
    CasaAcogida,
)

__all__ = [
    "router",
    "CasaAcogida",
    "VALID_COCHE_VALUES",
    "VALID_ESPECIE_VALUES",
    "AssignmentDecision",
    "FosterCapacityOverride",
    "assignment_service",
]
