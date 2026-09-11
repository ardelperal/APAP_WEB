"""Domain: EstanciaMaterial junction row.

Pure dataclass — no I/O. The mirror of the legacy
``TbAcogidaAnimalMaterial`` junction table. Mirrored from
``app/modules/materiales/service.py`` and re-exported under the
new ``domain/`` location; ``service.py`` re-imports from here in
PR 1 of the hexagonal refactor (issue #752) and the original
definition there is deleted.

The junction carries the assignment metadata (cantidad, notas)
but does NOT denormalize the material name — callers that need the
human-readable material name must JOIN via ``materiales.material``
separately. Keeping the dataclass narrow matches the precedent in
``app/modules/foster/assignment.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EstanciaMaterial:
    """A public service-row representation for ``estancia_materiales``.

    Attributes:
        id: UUID string from PostgreSQL ``gen_random_uuid()``.
        estancia_id: FK to ``acogidas.id`` — the foster stay.
        material_id: FK to ``materiales.id`` — the catalog item.
        cantidad: Integer > 0 (DB CHECK constraint + Python validator).
        activo: Soft-delete flag (defaults to True on create).
        notas: Optional free-text assignment notes.
        fecha_alta: Assignment timestamp (ISO string, server-generated).
    """

    id: str
    estancia_id: str
    material_id: str
    cantidad: int
    activo: bool = True
    notas: str | None = None
    fecha_alta: str | None = None


__all__ = ["EstanciaMaterial"]
