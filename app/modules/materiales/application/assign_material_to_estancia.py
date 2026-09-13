"""Use case: assign a material to an estancia (foster-material junction).

PR 3 of issue #752. Owns the FK-check policy the legacy
``assign_material_to_estancia`` enforced: the estancia must exist,
be active, and have no ``fecha_final``; the material must exist and
be active. These checks are NOT SQL queries the use case issues —
they are two new port methods (``estancia_is_open_and_active``,
``material_is_active``) the adapter implements. This keeps the
application layer 100% free of SQL while the use case still rejects
inactive / closed stays at the business-rule layer.

The use case short-circuits BEFORE issuing both probes: a closed
estancia fails fast without probing the material, and an inactive
material fails fast without issuing the INSERT.

Validation exception (``MaterialValidationError``) is reused from
``create_material`` so the route layer keeps the single error class
it already maps to HTTP 422.
"""

from __future__ import annotations

from app.modules.materiales.application.create_material import (
    MaterialValidationError,
)
from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.ports.materiales_port import MaterialesPort


def assign_material_to_estancia(
    materiales_port: MaterialesPort,
    *,
    estancia_id: str,
    material_id: str,
    cantidad: int = 1,
    notas: str | None = None,
) -> EstanciaMaterial:
    """Insert a junction row tying ``material_id`` to ``estancia_id``.

    Validates the estancia liveness BEFORE the material probe — a
    closed estancia fails fast without probing the material. The
    material probe runs only when the estancia probe succeeds.

    Returns the persisted :class:`EstanciaMaterial`. The adapter
    raises :class:`MaterialConflictError` when the partial unique
    index on the junction trips (a duplicate active assignment);
    the route layer maps it to HTTP 409.
    """
    if not materiales_port.estancia_is_open_and_active(estancia_id):
        raise MaterialValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"estancia_id debe apuntar a una estancia activa y sin "
            f"fecha_final ({estancia_id})"
        )
    if not materiales_port.material_is_active(material_id):
        raise MaterialValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"material_id debe apuntar a un material activo ({material_id})"
        )

    return materiales_port.assign_material_to_estancia(
        estancia_id=estancia_id,
        material_id=material_id,
        cantidad=cantidad,
        notas=notas,
    )


__all__ = ["assign_material_to_estancia"]
