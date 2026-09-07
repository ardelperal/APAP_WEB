"""Public surface of the ``sanidad`` module.

- ``service``: single-record CRUD for ``actuacion_sanitaria`` (HEALTH-01, #50).
- ``queries``: SQL builder seam per AGENTS §22 — the HEALTH-02 batch
  CTE is defined here so the SQL shape is testable without transport.
- ``batch_service``: orchestration for the HEALTH-02 batch endpoint
  (issue #51) — validates every record per D-24, atomically commits,
  and exposes staging preview via ``dry_run=true``. **Lazy-imported via
  ``__getattr__``** because importing ``app.core.catalogs`` from
  ``batch_service`` re-triggers the pre-existing
  ``app.core.schema_bootstrap`` ↔ ``app.core.adapters.insforge``
  circular import until ``app.main`` is loaded first. Lazy-loading
  breaks the dependency on this module's ``__init__`` ordering
  (HEALTH-05 / #54).
- ``routes``: HTTP layer for single-record CRUD (HEALTH-01).
- ``batch_routes``: HTTP layer for the HEALTH-02 batch endpoint.
  All data access delegates to the service layer; routes own no SQL.
- ``get_resumen_sanitario``: health-summary per-tipo latest-actuacion
  query (HEALTH-03, issue #52).
"""

from app.modules.sanidad import queries as sanidad_queries
from app.modules.sanidad import service as sanidad_service
from app.modules.sanidad.service import get_resumen_sanitario

__all__ = [
    "sanidad_service",
    "sanidad_batch_service",
    "sanidad_queries",
    "get_resumen_sanitario",
]


def __getattr__(name: str):  # PEP 562 module-level __getattr__
    """Lazy-load ``sanidad_batch_service`` on first attribute access.

    Importing ``batch_service`` eagerly triggers a chain that loops
    through ``app.core.catalogs`` -> ``app.core.schema_bootstrap``
    -> ``app.core.ports`` -> ``app.core.adapters.insforge`` and back,
    because ``StubAuthUsersPort`` also imports
    ``SqlStatement`` from ``app.core.schema_bootstrap``. The cycle
    only resolves once ``app.main`` has primed the relevant modules
    in ``sys.modules``. Defer the import to first attribute access so
    consumers like ``sanidad.periodicity`` (HEALTH-05) do not pull
    the cycle in.
    """
    if name == "sanidad_batch_service":
        from app.modules.sanidad import batch_service as sanidad_batch_service

        # Cache the attribute on the module so subsequent lookups skip
        # the lazy machinery.
        globals()["sanidad_batch_service"] = sanidad_batch_service
        return sanidad_batch_service
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
