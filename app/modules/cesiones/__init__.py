"""Owner-surrender (Cesión por Propietario) module.

Issue #41 (INTAKE-03). Routes consume ``service.create_cesion`` from
``app.modules.cesiones.routes``; the public surface is the
``create_cesion`` function and the ``Cesion`` dataclass.
"""

from app.modules.cesiones import service

__all__ = ["service"]
