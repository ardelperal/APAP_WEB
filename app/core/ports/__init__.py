"""Public port surface for the application's outbound dependencies.

Each port Protocol is the only contract the application layer sees for a
slice of functionality:

- :class:`CatalogosPort` — read access to the catalog (reference-data)
  tables.
- :class:`SchemaBootstrapPort` — DDL/seed operations executed by the
  schema-bootstrap flow, with :class:`SqlStatement` as its parameter DTO.

New ports (e.g. ``VolunteersPort``) live alongside these modules under
``app/core/ports/`` and re-export from here.
"""

from __future__ import annotations

from app.core.ports.catalogos_port import CatalogosPort
from app.core.ports.schema_bootstrap_port import SchemaBootstrapPort, SqlStatement

__all__ = ["CatalogosPort", "SchemaBootstrapPort", "SqlStatement"]
