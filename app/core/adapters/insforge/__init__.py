"""Concrete InsForge adapters that satisfy the application's ports.

This package is the ONLY place under ``app/core/`` that implements the
hexagonal ports against :mod:`app.core.insforge` (rule §31: domain
depends on Protocol, never on a concrete client). Each submodule owns
one port:

- ``catalogos_insforge_adapter`` — :class:`CatalogosPort` reads.
- ``schema_bootstrap_insforge_adapter`` — :class:`SchemaBootstrapPort`
  DDL/seed writes.

The adapter is the seam for rule §22 (query construction is its own
seam): SQL strings and parameter shaping live here, not in the
application layer. Each adapter:

1. Holds a :class:`SqlExecutor` injected by the DI layer.
2. Builds the SQL string and parameters per use case.
3. Maps the raw row dict to the frozen domain entity.

The adapter does NOT catch ``InsForgeError`` — the global handler
registered in ``app/core/insforge_error_handler.py`` translates any
unhandled transport error into a 502 at the FastAPI boundary. A unit
test that mocks the ``SqlExecutor`` to raise ``InsForgeError`` will
see the exception propagate untouched.
"""


from __future__ import annotations

from app.core.adapters.insforge.catalogos_insforge_adapter import (
    InsForgeCatalogosAdapter,
)
from app.core.adapters.insforge.schema_bootstrap_insforge_adapter import (
    InsForgeSchemaBootstrapAdapter,
)

__all__ = ["InsForgeCatalogosAdapter", "InsForgeSchemaBootstrapAdapter"]
