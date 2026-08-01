"""Public surface of the ``sanidad`` module.

- ``service``: single-record CRUD for ``actuacion_sanitaria`` (HEALTH-01, #50).
- ``queries``: SQL builder seam per AGENTS §22 — the HEALTH-02 batch
  CTE is defined here so the SQL shape is testable without transport.
- ``batch_service``: orchestration for the HEALTH-02 batch endpoint
  (issue #51) — validates every record per D-24, atomically commits,
  and exposes staging preview via ``dry_run=true``.
- ``terapia_service``: CRUD for ``terapias`` + ``recomendaciones``
  (HEALTH-05, issue #54).
- ``routes``: HTTP layer for single-record CRUD (HEALTH-01).
- ``batch_routes``: HTTP layer for the HEALTH-02 batch endpoint.
- ``terapia_routes``: HTTP layer for HEALTH-05 terapias CRUD.
  All data access delegates to the service layer; routes own no SQL.
- ``get_resumen_sanitario``: health-summary per-tipo latest-actuacion
  query (HEALTH-03, issue #52).
"""

from app.modules.sanidad import batch_service as sanidad_batch_service
from app.modules.sanidad import queries as sanidad_queries
from app.modules.sanidad import service as sanidad_service
from app.modules.sanidad import terapia_service as terapia_service
from app.modules.sanidad.service import get_resumen_sanitario

__all__ = [
    "sanidad_service",
    "sanidad_batch_service",
    "sanidad_queries",
    "terapia_service",
    "get_resumen_sanitario",
]
