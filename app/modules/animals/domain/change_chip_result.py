"""Result type for the chip-cascade saga (issue #29, LIFECYCLE-04).

``ChangeChipResult`` is the transport-neutral result of the chip saga.
The saga runs in a single transaction; on any failure the adapter
rolls back and returns ``success=False`` with the error message —
the route handler translates that into a 409 / 422 / 500
depending on the error class without leaking ``BackendError``
shape up to the application layer.

The ``updated_tables`` dict carries the row counts per touched table.
Since issue #916 (A-04) the saga touches only ``animales`` (the dependent
tables reference the animal through the ``animal_id`` FK and carry no chip
copy), so a successful change reports ``{"animals": <rows>}``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChangeChipResult:
    """Resultado del saga de cambio de chip.

    ``success=True``: la unidad de trabajo se confirmó atómicamente.
    ``success=False``: la operación se revirtió (rollback real vía
    ``transaction()``); ``error`` contiene la causa.
    ``updated_tables`` carries the per-touched-table row counts
    (only ``"animals"`` since issue #916).
    """

    success: bool
    old_chip: str
    new_chip: str
    updated_tables: dict[str, int] = field(default_factory=dict)
    error: str | None = None


__all__ = ["ChangeChipResult"]
