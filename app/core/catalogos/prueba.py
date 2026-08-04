"""Domain entity for a Prueba (medical test) catalog entry.

P1 fidelity (legacy ``TbNombrePruebas``): one row per *prueba sanitaria*
— a medical test or procedure performed on an animal. The legacy carries
``NombrePrueba``, ``Especie``, and ``Observaciones`` columns; the catalog
mirrors them as ``codigo`` (the legacy ``NombrePrueba`` literal),
``especie`` (lowercase legacy literals: ``'canina'``, ``'felina'``,
``'ambos'``), and ``observaciones`` (free-text hint about what to do
with the test — ``'analítica'``, ``'Vacuna'``, ``'Pon producto'``,
``'Pon Clínica'``).

In contrast to :class:`Motivo`, the ``especie`` values here are
**lowercase** because the legacy ``TbNombrePruebas`` stores them that
way. The catalog preserves the exact casing so the future sync layer
can join into the legacy byte-for-byte.
"""


from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Prueba:
    """Domain entity for a medical test in the catalog.

    Attributes:
        id: Server-assigned UUID; opaque to the domain.
        codigo: Natural key component — the legacy ``NombrePrueba``
            literal (Spanish spelling). Forms the natural key with
            ``especie``.
        nombre: Human-readable display name; equals ``codigo`` for the
            current 13-row seed.
        especie: Legacy ``Especie`` literal in lowercase (``'canina'``,
            ``'felina'``, or ``'ambos'``). Required.
        observaciones: Free-text hint about how to execute the test
            (legacy's ``Observaciones`` column). ``None`` when the
            legacy did not carry one.
        activo: ``True`` when the row is live.
        orden: Display order (lower first); ``None`` when unset.
    """

    id: str
    codigo: str
    nombre: str
    especie: str
    observaciones: str | None
    activo: bool
    orden: int | None


__all__ = ["Prueba"]
