"""Domain entity for a Periodicidad (recurrence rule) catalog entry.

P1 fidelity (legacy ``TbPruebasPeridicidad``): one row per *regla de
periodicidad* — the recurrence interval for a follow-up test on a
species. The legacy table is species-aware: the same test (e.g. "Vacuna
Polivalente") has different intervals for ``'canina'`` vs ``'felina'``,
and "Desparasitación" is every 3 months (not 12). The catalog uses
``(codigo, especie)`` as the natural key, mirroring
:class:`app.core.catalogos.prueba.Prueba`.

``especie`` may be ``None`` for a generic rule that applies to all
species (e.g. ``Esterilización``, which is a one-shot operation). The
seed enforces a NOT NULL constraint on ``id``/``codigo``/``nombre``
but leaves ``especie`` nullable.

``periodicidad_meses`` semantics:

- ``None``  — one-shot operation (e.g. Esterilización); not recurring.
- ``> 0``   — months between recurring follow-ups.
"""


from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Periodicidad:
    """Domain entity for a periodicity rule in the catalog.

    Attributes:
        id: Server-assigned UUID; opaque to the domain.
        codigo: Natural key component — the test name (legacy
            ``NombrePrueba`` literal). Forms the natural key with
            ``especie``.
        nombre: Human-readable display name; equals ``codigo``.
        especie: Legacy ``Especie`` literal in lowercase (``'canina'``,
            ``'felina'``), or ``None`` for a generic rule that applies
            to all species.
        periodicidad_meses: Months between recurring follow-ups; ``None``
            for a one-shot operation (e.g. Esterilización).
        activo: ``True`` when the row is live.
        orden: Display order (lower first); ``None`` when unset.
    """

    id: str
    codigo: str
    nombre: str
    especie: str | None
    periodicidad_meses: int | None
    activo: bool
    orden: int | None


__all__ = ["Periodicidad"]
