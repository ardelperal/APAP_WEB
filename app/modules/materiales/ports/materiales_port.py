"""Hexagonal port for the materiales module (FOSTER-04, issue #46).

The application layer and routes depend on this ``Protocol``; the
LocalBackend adapter (PR 2 of issue #752) implements it. The port
carries one method per public use case from the legacy
``service.py`` and ``estancia_material_service.py``.

Hexagonal taxonomy:

- **Domain**     (:mod:`app.modules.materiales.domain`)         — entities, no I/O.
- **Port**       (this module)                                  — abstract surface.
- **Application**(:mod:`app.modules.materiales.application`)   — use cases (PR 3).
- **Adapter**    (:mod:`app.modules.materiales.adapters.local_backend`) — LocalBackend impl (PR 2).
- **DI**         (:mod:`app.modules.materiales.di`)             — wiring (PR 4).

Rule §31 (domain services depend on Protocol abstractions): every
method here takes no concrete backend client; the adapter chooses
its own transport. Rule §22 (SQL/service separation): the SQL
lives in the adapter, not in the port.

The port imports the domain dataclasses (``Material``,
``EstanciaMaterial``) and the domain exception (``MaterialConflictError``)
for return-type and raise-type signatures; that is the only inward
dependency. No transport import is allowed here — the architectural
pin test in ``tests/test_slice_materiales_architecture.py`` enforces this.
"""

from __future__ import annotations

from typing import Protocol

from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.domain.exceptions import MaterialConflictError
from app.modules.materiales.domain.material import Material


class MaterialesPort(Protocol):
    """Abstract surface for the materiales bounded context.

    Eight methods cover the full public surface of the legacy
    ``service.py`` (five catalog CRUD) plus
    ``estancia_material_service.py`` (three junction CRUD). The
    methods preserve the legacy signatures so callers and existing
    tests keep working unchanged once the DI swaps the concrete
    service for the port-backed adapter.

    Implementations:

    - Production: ``app/modules/materiales/adapters/local_backend/materiales_local_backend_adapter.py``
      (lands in PR 2 of issue #752).
    - Test fakes: in-memory fakes that satisfy the same Protocol
      without spinning up Postgres or LocalBackend.
    """

    def create_material(self, params: dict) -> Material:
        """Insert a new material in the catalog and return the persisted row.

        Mirrors ``app.modules.materiales.service.create_material`` (Scenario 2
        in spec #15894). Validates required text fields BEFORE SQL; on a
        ``UNIQUE (material, tamano, color)`` violation raises
        :class:`MaterialConflictError`.
        """
        ...

    def get_material_by_id(self, material_id: str) -> Material | None:
        """Return one material by id (active or inactive), or ``None``.

        Mirrors ``app.modules.materiales.service.get_material_by_id``.
        """
        ...

    def list_materials(self, activos_solo: bool = True) -> list[Material]:
        """Return the catalog ordered by ``fecha_alta DESC``.

        Mirrors ``app.modules.materiales.service.list_materials``.
        ``activos_solo=False`` includes soft-deleted rows for the audit view.
        """
        ...

    def update_material(
        self, material_id: str, params: dict
    ) -> Material | None:
        """Update a material's text fields and bump ``updated_at``.

        Mirrors ``app.modules.materiales.service.update_material``. Returns
        ``None`` when the row does not exist; raises
        :class:`MaterialConflictError` on natural-key collision.
        """
        ...

    def deactivate_material(self, material_id: str) -> bool:
        """Soft-delete a material and cascade the deactivation to its active junctions.

        Mirrors ``app.modules.materiales.service.deactivate_material``
        (Scenario 6 in spec #15894). Idempotent: returns ``False`` when the
        row does not exist OR was already inactive.
        """
        ...

    def assign_material_to_estancia(
        self,
        estancia_id: str,
        material_id: str,
        cantidad: int = 1,
        notas: str | None = None,
    ) -> EstanciaMaterial:
        """Insert a junction row tying ``material_id`` to ``estancia_id``.

        Mirrors ``app.modules.materiales.estancia_material_service.assign_material_to_estancia``.
        Validates estancia-open-and-active and material-active BEFORE the
        INSERT; raises :class:`ValueError` on invalid FK (route maps to 422)
        and :class:`MaterialConflictError` on duplicate active assignment
        (route maps to 409).
        """
        ...

    def list_materials_for_estancia(
        self, estancia_id: str, activos_solo: bool = True
    ) -> list[EstanciaMaterial]:
        """Return junction rows for ``estancia_id`` ordered by fecha_alta DESC.

        Mirrors ``app.modules.materiales.estancia_material_service.list_materials_for_estancia``.
        """
        ...

    def remove_material_from_estancia(self, junction_id: str) -> bool:
        """Atomically soft-delete a single junction row.

        Mirrors ``app.modules.materiales.estancia_material_service.remove_material_from_estancia``.
        Idempotent: returns ``False`` when missing or already inactive.
        """
        ...


__all__ = [
    "EstanciaMaterial",
    "Material",
    "MaterialConflictError",
    "MaterialesPort",
]
