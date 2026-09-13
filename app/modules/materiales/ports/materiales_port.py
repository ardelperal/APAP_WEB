"""Hexagonal port for the materiales module (FOSTER-04, issue #46).

The application layer and routes depend on this ``Protocol``; the
LocalBackend adapter (PR 2 of issue #752) implements it. The port
carries one method per public use case from the application
layer (:mod:`app.modules.materiales.application`).

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

    Eight methods cover the application layer's public surface
    (five catalog CRUD use cases in
    :mod:`app.modules.materiales.application` plus three junction
    CRUD use cases in the same module). The two FK-probe methods
    added in PR 3 of #752 (``estancia_is_open_and_active`` and
    ``material_is_active``) let the application use case enforce
    the same policy the legacy ``_validate_*`` helpers did without
    importing SQL into ``application/``.

    Implementations:

    - Production: ``app/modules/materiales/adapters/local_backend/materiales_local_backend_adapter.py``
      (lands in PR 2 of issue #752).
    - Test fakes: in-memory fakes that satisfy the same Protocol
      without spinning up Postgres or LocalBackend.
    """

    def create_material(self, params: dict) -> Material:
        """Insert a new material in the catalog and return the persisted row.

        Mirrors ``app.modules.materiales.application.create_material`` (Scenario 2
        in spec #15894). Validates required text fields BEFORE SQL; on a
        ``UNIQUE (material, tamano, color)`` violation raises
        :class:`MaterialConflictError`.
        """
        ...

    def get_material_by_id(self, material_id: str) -> Material | None:
        """Return one material by id (active or inactive), or ``None``.

        Mirrors ``app.modules.materiales.application.get_material_by_id``.
        """
        ...

    def list_materials(self, activos_solo: bool = True) -> list[Material]:
        """Return the catalog ordered by ``fecha_alta DESC``.

        Mirrors ``app.modules.materiales.application.list_materials``.
        ``activos_solo=False`` includes soft-deleted rows for the audit view.
        """
        ...

    def update_material(
        self, material_id: str, params: dict
    ) -> Material | None:
        """Update a material's text fields and bump ``updated_at``.

        Mirrors ``app.modules.materiales.application.update_material``. Returns
        ``None`` when the row does not exist; raises
        :class:`MaterialConflictError` on natural-key collision.
        """
        ...

    def deactivate_material(self, material_id: str) -> bool:
        """Soft-delete a material and cascade the deactivation to its active junctions.

        Mirrors ``app.modules.materiales.application.deactivate_material``
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

        Mirrors ``app.modules.materiales.application.assign_material_to_estancia``.
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

        Mirrors ``app.modules.materiales.application.list_materials_for_estancia``.
        """
        ...

    def remove_material_from_estancia(self, junction_id: str) -> bool:
        """Atomically soft-delete a single junction row.

        Mirrors ``app.modules.materiales.application.remove_material_from_estancia``.
        Idempotent: returns ``False`` when missing or already inactive.
        """
        ...

    def estancia_is_open_and_active(self, estancia_id: str) -> bool:
        """FK probe: ``True`` iff the estancia exists, is active, and has no ``fecha_final``.

        Added in PR 3 of issue #752 so the application-layer assign
        use case can enforce the same policy the legacy
        ``_validate_estancia_open_and_active`` enforced, without
        importing SQL into ``application/``. The adapter runs a
        single SELECT against the estancia table that owns the FK;
        the application treats the result as a bool.
        """
        ...

    def material_is_active(self, material_id: str) -> bool:
        """FK probe: ``True`` iff the material exists and is active.

        Mirrors ``_validate_material_active`` for the application
        layer. Added in PR 3 of issue #752.
        """
        ...


__all__ = [
    "EstanciaMaterial",
    "Material",
    "MaterialConflictError",
    "MaterialesPort",
]
