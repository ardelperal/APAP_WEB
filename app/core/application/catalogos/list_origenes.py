"""Use case: list all active Origen entries.

Thin orchestrator over :class:`CatalogosPort`. Hexagonal contract:

- Inputs: the port (depends on :class:`CatalogosPort` Protocol, not on
  any concrete backend).
- Outputs: a list of :class:`Origen` entities (the domain value object).
- Side effects: none.

The adapter that implements the port is responsible for the actual
SQL round-trip; this use case only delegates. Splitting the use case
into its own module (one function per file) keeps the orchestrator
identifiable on a single-page code-graph query: ``codegraph_explore
list_origenes`` returns the delegating body of THIS function — not the
SQL-building body of the adapter.
"""


from __future__ import annotations

from app.core.catalogos.origen import Origen
from app.core.ports.catalogos_port import CatalogosPort


def list_origenes(port: CatalogosPort) -> list[Origen]:
    """Return all active origenes ordered by their display order.

    Args:
        port: The catalog port implementation injected by the DI
            layer (``app/core/di/catalogos_di.py``).

    Returns:
        All active :class:`Origen` rows, ordered by ``orden`` (NULLS
        LAST) then ``codigo``. Returns an empty list when no rows are
        active — the caller does NOT need to special-case the empty
        result.
    """
    return port.list_origenes()


__all__ = ["list_origenes"]
