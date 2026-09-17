"""Domain entities for the contratos slice.

Public surface:

- :class:`TipoContrato` (eight contract types).
- :class:`Plantilla` and :class:`PlantillaInvalidaError` (template body +
  grammar validation).
- :class:`SolicitudContrato` (the variable bundle the render use
  case receives — animal + voluntario + owner context).

The domain layer is transport-free (rule §31). It does NOT import
``app.core.local_backend`` or any HTTP/DB driver. The pin test
``tests/test_slice_contratos_architecture.py`` enforces this.
"""

from __future__ import annotations

from app.modules.contratos.domain.plantilla import (
    Plantilla,
    PlantillaInvalidaError,
    validar_gramatica,
)
from app.modules.contratos.domain.solicitud import SolicitudContrato
from app.modules.contratos.domain.tipos_contrato import TipoContrato

__all__ = [
    "Plantilla",
    "PlantillaInvalidaError",
    "SolicitudContrato",
    "TipoContrato",
    "validar_gramatica",
]
