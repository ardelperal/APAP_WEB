"""Domain entities for the catalog (reference-data) tables.

One module per catalog entity, mirroring the 5 seed tables in
``app/core/catalogs.py`` (entries migrated from the legacy Access
database ``TbOrigenEntrada``, ``TbMotivosEntrada``, ``TbNombrePruebas``,
``TbPruebasPeridicidad``, and ``TbPlantillas``).

Hexagonal layout (refactor/hexagonal-slice-catalogos):

- This package (``app.core.catalogos``)                  — pure dataclasses; no
  I/O imports, no SQL, no LocalBackend dependency. The single source of
  truth for the in-memory shape of each catalog row.
- ``app.core.ports.catalogos_port.CatalogosPort``        — the ``Protocol``
  the application layer depends on; the adapter implements it.
- ``app.core.application.catalogos.list_*``              — use-case functions
  that delegate to the port.
- ``app.core.adapters.local_backend.catalogos_local_backend_adapter`` — the only
  module that imports ``app.core.local_backend`` and shapes the SQL.
- ``app.core.di.catalogos_di.get_catalogos_port``        — FastAPI wiring.

.. note::

   The package is named ``app.core.catalogos`` (not ``app.core.domain.catalogos``)
   to avoid colliding with the existing ``app/core/domain.py`` module — the
   project already has a flat ``domain`` module with the bootstrap
   ``ensure_domain_schema`` function imported by ``app/main.py``. The
   follow-up PR that retires ``app/core/domain.py`` will move this package
   under ``app/core/domain/`` per the original task spec.

All five entities are ``frozen=True`` dataclasses with ``slots=True``.
They are value objects: equality is structural, they are immutable, and
attribute access is the only API.
"""


from __future__ import annotations

from app.core.catalogos.motivo import Motivo
from app.core.catalogos.origen import Origen
from app.core.catalogos.periodicidad import Periodicidad
from app.core.catalogos.prueba import Prueba
from app.core.catalogos.tipo_contrato import TipoContrato

__all__ = [
    "Motivo",
    "Origen",
    "Periodicidad",
    "Prueba",
    "TipoContrato",
]
