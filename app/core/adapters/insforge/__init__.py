"""Concrete InsForge adapter that satisfies :class:`CatalogosPort`.

This module is the ONLY place under ``app/core/`` that imports
:mod:`app.core.insforge` for catalog reads (rule §31: domain depends
on Protocol, never on a concrete client). The adapter:

1. Holds a :class:`SqlExecutor` injected by the DI layer.
2. Builds the SQL string and parameters per use case (rule §22:
   query construction is its own seam — the adapter is the seam).
3. Maps the raw row dict to the frozen domain entity.

The SQL constants and the row → entity mapping live here, not in the
domain package, because that is the convention the rest of the codebase
follows (e.g. ``app/modules/animals/photo_service.py`` owns its
``_PhotoClient`` Protocol and the storage row mapping). The domain
package is pure dataclasses.

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

__all__ = ["InsForgeCatalogosAdapter"]
