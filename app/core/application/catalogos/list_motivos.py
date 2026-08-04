"""Use case: list all active Motivo entries.

Thin orchestrator over :class:`CatalogosPort`. The species-aware
ordering (grouped by ``especie``) is the responsibility of the adapter
that implements the port; this use case only delegates.
"""


from __future__ import annotations

from app.core.catalogos.motivo import Motivo
from app.core.ports.catalogos_port import CatalogosPort


def list_motivos(port: CatalogosPort) -> list[Motivo]:
    """Return all active motivos grouped by ``especie``.

    Args:
        port: The catalog port implementation injected by the DI
            layer (``app/core/di/catalogos_di.py``).

    Returns:
        All active :class:`Motivo` rows, ordered by ``orden`` (NULLS
        LAST) then ``especie`` then ``codigo``. Empty when no rows
        are active.
    """
    return port.list_motivos()


__all__ = ["list_motivos"]
