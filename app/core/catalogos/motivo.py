"""Domain entity for a Motivo (reason) catalog entry.

P1 fidelity (legacy ``TbMotivosEntrada``): one row per *motivo de entrada* —
the reason an animal entered the protectora. The legacy carries
``Motivo`` and ``Especie`` columns; the catalog mirrors them as
``codigo`` (the legacy ``Motivo`` literal) and ``especie`` (the legacy
``Especie`` literal). The natural key is ``(codigo, especie)`` because
the same Motivo can appear with different Especie values (``'De colonia
de gatos'`` is the only FELINA-only motivo in the current seed).

``especie`` is a closed set of legacy literals: ``'AMBOS'``,
``'CANINA'``, ``'FELINA'``. The legacy uses uppercase; the catalog
preserves that exact casing so the syncing layer can join into the
legacy byte-for-byte.
"""


from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Motivo:
    """Domain entity for a reason of entry in the catalog.

    Attributes:
        id: Server-assigned UUID; opaque to the domain.
        codigo: Natural key component — the legacy ``Motivo`` literal
            (Spanish spelling). Forms the natural key together with
            ``especie``.
        nombre: Human-readable display name; equals ``codigo`` for the
            current 21-row seed.
        especie: Legacy ``Especie`` literal (``'AMBOS'``, ``'CANINA'``,
            or ``'FELINA'``). Required — the seed enforces a NOT NULL
            constraint.
        activo: ``True`` when the row is live.
        orden: Display order (lower first); ``None`` when unset.
    """

    id: str
    codigo: str
    nombre: str
    especie: str
    activo: bool
    orden: int | None


__all__ = ["Motivo"]
