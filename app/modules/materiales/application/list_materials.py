"""Use case: list the catalog (active by default; PR 3 of #752).

``activos_solo=False`` exposes the admin/audit view. Pure delegation.
"""

from __future__ import annotations

from app.modules.materiales.domain.material import Material
from app.modules.materiales.ports.materiales_port import MaterialesPort


def list_materials(
    materiales_port: MaterialesPort,
    activos_solo: bool = True,
) -> list[Material]:
    return materiales_port.list_materials(activos_solo=activos_solo)


__all__ = ["list_materials"]
