"""Owner-surrender (Cesion por Propietario) module.

Issue #41 (INTAKE-03). Hexagonal layout:

- ``domain/`` — ``Cesion``, ``Contrato``, ``CesionConflictError``
- ``ports/`` — ``CesionesPort``
- ``application/`` — ``create_cesion``, ``get_cesion_by_entrada_id``, ``list_cesiones``
- ``adapters/insforge/`` — ``CesionesInsforgeAdapter``
- ``di/`` — ``get_cesiones_port`` generator

Routes consume the port via ``get_cesiones_port`` (DI). The service layer
remains as the InsForge-backed adapter for backward compatibility.
"""

from app.modules.cesiones import service
from app.modules.cesiones.domain.cesion import Cesion, CesionConflictError, Contrato

__all__ = ["service", "Cesion", "Contrato", "CesionConflictError"]
