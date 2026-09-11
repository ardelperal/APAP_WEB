"""Domain: Material catalog row.

Pure dataclass — no I/O. The mirror of the legacy ``TbMaterial``
table per AGENTS.md premise P1 (fidelity to legacy). Mirrored from
``app/modules/materiales/service.py`` and re-exported under the
new ``domain/`` location; ``service.py`` re-imports from here in
PR 1 of the hexagonal refactor (issue #752) and the original
definition there is deleted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Material:
    """A public service-row representation for ``materiales``.

    Attributes:
        id: UUID string from PostgreSQL ``gen_random_uuid()``.
        material: Required text — natural key part 1.
        tamano: Required text — natural key part 2.
        color: Required text — natural key part 3.
        activo: Soft-delete flag (defaults to True on create).
        observaciones: Optional free-text legacy field (TbMaterial.Observaciones).
        fecha_alta: INSERT timestamp (ISO string, server-generated).
        fecha_baja: Soft-delete timestamp (None when activo=True).
        updated_at: Last-write timestamp (server-bumped on every UPDATE).
    """

    id: str
    material: str
    tamano: str
    color: str
    activo: bool = True
    observaciones: str | None = None
    fecha_alta: str | None = None
    fecha_baja: str | None = None
    updated_at: str | None = None


__all__ = ["Material"]
