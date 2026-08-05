"""Use case: list all active Periodicidad entries.

Thin orchestrator over :class:`CatalogosPort`. The recurrence rules
are species-aware and ``periodicidad_meses`` may be ``None`` for
one-shot operations (e.g. Esterilización); the adapter is responsible
for ordering and qualifying ``NULL`` values.
"""


from __future__ import annotations

from app.core.catalogos.periodicidad import Periodicidad
from app.core.ports.catalogos_port import CatalogosPort


def list_periodicidad(port: CatalogosPort) -> list[Periodicidad]:
    """Return all active periodicidades ordered by ``orden`` then ``codigo``.

    Args:
        port: The catalog port implementation injected by the DI
            layer (``app/core/di/catalogos_di.py``).

    Returns:
        All active :class:`Periodicidad` rows. Empty when no rows are
        active.
    """
    return port.list_periodicidad()


__all__ = ["list_periodicidad"]
