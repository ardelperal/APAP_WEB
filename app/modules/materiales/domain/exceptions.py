"""Domain exceptions for the materiales module.

Pure exception classes — no I/O, no transport. Moved here from
``app/modules/materiales/service.py`` as part of the hexagonal
refactor (issue #752, PR 1 of 5). ``service.py`` re-imports these
so the public surface (and every test that imports the exception
from ``app.modules.materiales.service``) keeps working unchanged
until PR 5 deletes ``service.py``.
"""

from __future__ import annotations


class MaterialConflictError(ValueError):
    """Raised when a natural-key conflict occurs on the catalog or junction.

    The ``UNIQUE (material, tamano, color)`` constraint on
    ``materiales`` and the partial unique index
    ``estancia_materiales_active_unique`` on
    ``(estancia_id, material_id) WHERE activo = true`` are DB-enforced
    (P1 fidelity to legacy ``TbMaterial`` and
    ``TbAcogidaAnimalMaterial``). A duplicate INSERT raises
    PostgreSQL 23505 which the LocalBackend proxy surfaces as
    ``BackendError(409, ...)``. The service catches that and re-raises
    as ``MaterialConflictError`` with a Spanish actionable message so
    the route layer can map it to HTTP 409. Mirrors the
    ``EntradaConflictError`` / ``AcogidaConflictError`` precedent.
    """


__all__ = ["MaterialConflictError"]
