"""Use case: list all active Prueba entries.

Thin orchestrator over :class:`CatalogosPort`. Test rows are
species-aware (lowercase ``especie`` values); the column ordering is
the responsibility of the adapter.
"""


from __future__ import annotations

from app.core.catalogos.prueba import Prueba
from app.core.ports.catalogos_port import CatalogosPort


def list_pruebas(port: CatalogosPort) -> list[Prueba]:
    """Return all active pruebas ordered by ``orden`` then ``codigo``.

    Args:
        port: The catalog port implementation injected by the DI
            layer (``app/core/di/catalogos_di.py``).

    Returns:
        All active :class:`Prueba` rows. Empty when no rows are active.
    """
    return port.list_pruebas()


__all__ = ["list_pruebas"]
