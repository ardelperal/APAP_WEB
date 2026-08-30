"""Port interface for the Cesiones slice.

Expressed in domain vocabulary; no InsForge, no SQL.
runtime_checkable so the DI generator can validate adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.modules.cesiones.domain.cesion import Cesion, Contrato


@runtime_checkable
class CesionesPort(Protocol):
    """Hexagonal port for the cesión por propietario workflow.

    Issue #41 (INTAKE-03).
    """

    def create_cesion(self, params: dict[str, Any]) -> tuple[Cesion, Contrato]:
        """Create an owner-surrender record and its linked contrato.

        Raises:
            ValueError: required fields blank, entrada_id not found,
                or catalog misconfigured.
            CesionConflictError: the entrada already has a cesión
                (1-a-1 UNIQUE FK violated).
        """
        ...

    def get_cesion_by_entrada_id(self, entrada_id: str) -> Cesion | None:
        """Return the cesión linked to an entrada, or None if missing."""
        ...

    def list_cesiones(self) -> list[Cesion]:
        """Return all cesiones, newest first."""
        ...
