"""Use case: list junction rows for a given estancia (PR 3 of #752).

``activos_solo=False`` exposes the historical view. Pure delegation.
"""

from __future__ import annotations

from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.ports.materiales_port import MaterialesPort


def list_materials_for_estancia(
    materiales_port: MaterialesPort,
    estancia_id: str,
    activos_solo: bool = True,
) -> list[EstanciaMaterial]:
    return materiales_port.list_materials_for_estancia(
        estancia_id=estancia_id, activos_solo=activos_solo
    )


__all__ = ["list_materials_for_estancia"]
