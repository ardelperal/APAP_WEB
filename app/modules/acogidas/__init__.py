"""Estancias de Acogida module (FOSTER-02, #44).

Exports the service + the router so the rest of the app can do
``from app.modules.acogidas import service, router``.

The router import is deferred below to avoid a circular dependency
between ``app.modules.acogidas.routes`` (which imports the service)
and the module-level re-export. Same pattern as FOSTER-01
(``app/modules/foster/__init__.py``).
"""

from app.modules.acogidas.routes import router
from app.modules.acogidas.service import (
    Acogida,
    AcogidaConflictError,
    compute_duracion,
    is_active,
)

__all__ = [
    "router",
    "Acogida",
    "AcogidaConflictError",
    "compute_duracion",
    "is_active",
]
