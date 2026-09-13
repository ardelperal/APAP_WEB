"""Use case: soft-delete a material and cascade (PR 3 of #752).

Idempotent: returns ``False`` when the row is missing or already
inactive. The cascade UPDATE runs inside the port method.
"""

from __future__ import annotations

from app.modules.materiales.ports.materiales_port import MaterialesPort


def deactivate_material(
    materiales_port: MaterialesPort, material_id: str
) -> bool:
    return materiales_port.deactivate_material(material_id)


__all__ = ["deactivate_material"]
