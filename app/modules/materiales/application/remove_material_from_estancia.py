"""Use case: soft-delete one junction row owned by ``estancia_id`` (PR 3 of #752).

Issue #919 (audit finding A-07): the delete is ownership-scoped — the
port only deactivates the junction when it belongs to ``estancia_id``;
otherwise it returns ``False`` and the route maps that to 404.
Idempotent — pure delegation to the port.
"""

from __future__ import annotations

from app.modules.materiales.ports.materiales_port import MaterialesPort


def remove_material_from_estancia(
    materiales_port: MaterialesPort, estancia_id: str, junction_id: str
) -> bool:
    return materiales_port.remove_material_from_estancia(estancia_id, junction_id)


__all__ = ["remove_material_from_estancia"]
