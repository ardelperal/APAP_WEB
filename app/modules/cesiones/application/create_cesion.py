"""Use case: create a new owner-surrender record (cesión por propietario).

Slice: app/modules/cesiones (hexagonal migration).
Single application-layer entry point for hexagonal cesión creation.
Delegates to :class:`~app.modules.cesiones.ports.cesiones_port.CesionesPort`
so the application code stays transport-agnostic (AGENTS.md §31).

Validation rules preserved from the retired legacy service layer:
- ``entrada_id`` is mandatory and must reference an existing entrada.
- ``numero_contrato`` is mandatory (legacy contract numbering).
- ``nombre_representante`` is mandatory; the legacy DDL allowed NULL but
  the web narrows this to match P1-fidelity requirements.
- ``CesionConflictError`` propagates from the port when the entrada
  already has a cesión (1-a-1 UNIQUE FK), translated to HTTP 409 by the route.
"""

from __future__ import annotations

from typing import Any

from app.modules.cesiones.domain.cesion import Cesion, Contrato
from app.modules.cesiones.ports.cesiones_port import CesionesPort


def create_cesion(
    port: CesionesPort,
    params: dict[str, Any],
) -> tuple[Cesion, Contrato]:
    """Create a cesión por propietario and its linked contrato.

    Validates required fields before delegating to the port.
    The adapter is responsible for FK checks and for raising
    :class:`CesionConflictError <app.modules.cesiones.domain.cesion.CesionConflictError>`
    when the entrada already has a cesión.
    """
    # Mirror the service-level validation so ValueError propagates cleanly.
    _require_non_blank(params, "entrada_id")
    _require_non_blank(params, "numero_contrato")
    _require_non_blank(params, "nombre_representante")
    return port.create_cesion(params)


def _require_non_blank(params: dict[str, Any], field: str) -> str:
    value = str(params.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required and cannot be empty")
    return value


__all__ = ["create_cesion"]
