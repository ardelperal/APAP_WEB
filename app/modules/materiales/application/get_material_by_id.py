"""Use case: fetch a single material by id (PR 3 of #752).

Pure delegation — the adapter handles the SQL lookup; the route
layer maps ``Material | None`` to HTTP 200/404.
"""

from __future__ import annotations

from app.modules.materiales.domain.material import Material
from app.modules.materiales.ports.materiales_port import MaterialesPort


def get_material_by_id(
    materiales_port: MaterialesPort, material_id: str
) -> Material | None:
    return materiales_port.get_material_by_id(material_id)


__all__ = ["get_material_by_id"]
