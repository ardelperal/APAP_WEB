"""Domain entity for an Origen (origin) catalog entry.

P1 fidelity (legacy ``TbOrigenEntrada``): one row per *origen de entrada* —
the source channel by which an animal entered the protectora. The legacy
table has a single text column ``Origen``; the catalog carries the legacy
literal as ``codigo`` (the natural key) plus a human-readable ``nombre``
and an ``orden`` field for deterministic UI ordering.

A ``descripcion`` is optional and a future-extension column (no legacy
equivalent). The ``activo`` flag mirrors the legacy dormant-state column
and gates whether the entry is surfaced in dropdowns.
"""


from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Origen:
    """Domain entity for an origin of entry in the catalog.

    Attributes:
        id: Server-assigned UUID; opaque to the domain.
        codigo: Natural key; the legacy ``Origen`` literal (Spanish spelling).
        nombre: Human-readable display name; equals ``codigo`` for the
            current 7-row seed but is a separate column to allow future
            divergence (e.g. a short code + a long form).
        descripcion: Optional free-text description; ``None`` when the
            legacy did not carry a description.
        activo: ``True`` when the row is live; ``False`` rows are hidden
            from read paths but kept for audit.
        orden: Display order (lower first); ``None`` when the operator
            has not set an explicit order, in which case the read path
            falls back to alphabetical by ``codigo``.
    """

    id: str
    codigo: str
    nombre: str
    descripcion: str | None
    activo: bool
    orden: int | None


__all__ = ["Origen"]
