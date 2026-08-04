"""Hexagonal port for the catalog (reference-data) tables.

The application layer depends on this :class:`Protocol`; the InsForge
adapter implements it. Tests can implement it with an in-memory fake
without spinning up transport or HTTP.

The port carries one method per catalog read use case (origenes,
motivos, pruebas, periodicidad, tipos_contrato). The write-side
(``ensure_catalogs``) is intentionally OUT of this port: it is a
bootstrap concern owned by the lifespan (``app/main.py``), not a
domain use case, and migrating it to the hexagonal pattern is a
separate follow-up.

Hexagonal taxonomy:

- **Domain**     (:mod:`app.core.catalogos`)               — entities, no I/O.
- **Port**       (this module)                              — abstract surface.
- **Application**(:mod:`app.core.application.catalogos`)   — use cases.
- **Adapter**    (:mod:`app.core.adapters.insforge`)       — InsForge impl.
- **DI**         (:mod:`app.core.di.catalogos_di`)          — wiring.

Rule §31 (domain services depend on Protocol abstractions): every
method here takes no concrete backend client; the adapter chooses its
own transport. Rule §22 (SQL/service separation): the SQL lives in the
adapter, not in the port.
"""


from __future__ import annotations

from typing import Protocol

from app.core.catalogos.motivo import Motivo
from app.core.catalogos.origen import Origen
from app.core.catalogos.periodicidad import Periodicidad
from app.core.catalogos.prueba import Prueba
from app.core.catalogos.tipo_contrato import TipoContrato


class CatalogosPort(Protocol):
    """Abstract surface for reading catalog (reference-data) tables.

    All five methods are pure read paths: they take no parameters
    besides ``self`` and return a list of frozen dataclasses. The
    first call after a cold start incurs the cost of bootstrapping
    the catalog rows (see ``ensure_catalogs`` in
    ``app/core/catalogs.py``); subsequent reads are served by the
    existing rows.

    Implementations:

    - :class:`app.core.adapters.insforge.catalogos_insforge_adapter.InsForgeCatalogosAdapter`
      — production adapter, talks to InsForge via :class:`SqlExecutor`.
    - Test fakes (in ``tests/``) — in-memory list-backed fakes for
      unit tests on the application layer.
    """

    def list_origenes(self) -> list[Origen]:
        """Return all active origenes ordered by ``orden`` then ``codigo``."""
        ...

    def list_motivos(self) -> list[Motivo]:
        """Return all active motivos grouped by ``especie``."""
        ...

    def list_pruebas(self) -> list[Prueba]:
        """Return all active pruebas ordered by ``orden`` then ``codigo``."""
        ...

    def list_periodicidad(self) -> list[Periodicidad]:
        """Return all active periodicidades ordered by ``orden`` then ``codigo``."""
        ...

    def list_tipos_contrato(self) -> list[TipoContrato]:
        """Return all active contract-template types for Fase 7."""
        ...


__all__ = ["CatalogosPort"]
