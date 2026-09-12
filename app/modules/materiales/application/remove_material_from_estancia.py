"""Use case: soft-delete a single junction row (PR 3 of #752).

Idempotent — pure delegation to the port.
"""

from __future__ import annotations

from app.modules.materiales.ports.materiales_port import MaterialesPort


def remove_material_from_estancia(
    materiales_port: MaterialesPort, junction_id: str
) -> bool:
    return materiales_port.remove_material_from_estancia(junction_id)


__all__ = ["remove_material_from_estancia"]
