"""Use case: list all active TipoContrato entries.

Thin orchestrator over :class:`CatalogosPort`. These rows feed the
contract-template engine planned for Fase 7 of ``docs/roadmap.md``.
"""


from __future__ import annotations

from app.core.catalogos.tipo_contrato import TipoContrato
from app.core.ports.catalogos_port import CatalogosPort


def list_tipos_contrato(port: CatalogosPort) -> list[TipoContrato]:
    """Return all active contract-template types.

    Args:
        port: The catalog port implementation injected by the DI
            layer (``app/core/di/catalogos_di.py``).

    Returns:
        All active :class:`TipoContrato` rows. Empty when no rows are
        active.
    """
    return port.list_tipos_contrato()


__all__ = ["list_tipos_contrato"]
