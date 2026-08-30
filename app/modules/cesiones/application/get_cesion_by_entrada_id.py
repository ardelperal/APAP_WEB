"""Use case: retrieve a cesión by its entrada_id.

Slice: app/modules/cesiones (hexagonal migration).
Delegates to :class:`~app.modules.cesiones.ports.cesiones_port.CesionesPort`.
"""

from __future__ import annotations

from app.modules.cesiones.domain.cesion import Cesion
from app.modules.cesiones.ports.cesiones_port import CesionesPort


def get_cesion_by_entrada_id(
    port: CesionesPort,
    entrada_id: str,
) -> Cesion | None:
    """Return the cesión linked to an entrada, or None when missing."""
    return port.get_cesion_by_entrada_id(entrada_id)


__all__ = ["get_cesion_by_entrada_id"]
