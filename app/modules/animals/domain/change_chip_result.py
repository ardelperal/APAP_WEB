"""Result type for the chip-cascade saga (issue #29, LIFECYCLE-04).

``ChangeChipResult`` is the transport-neutral result of the chip saga.
The saga runs in a single transaction; on any failure the adapter
rolls back and returns ``success=False`` with the error message —
the route handler translates that into a 409 / 422 / 500
depending on the error class without leaking ``BackendError``
shape up to the application layer.

The ``updated_tables`` dict carries the row counts per table
(``"animals"``, ``"entradas"``, etc.) so the operator can audit
the blast radius of a successful change without re-querying.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ChangeChipResult:
    """Resultado del saga de cambio de chip.

    ``success=True``: todos los registros se actualizaron atómicamente.
    ``success=False``: la operación se revirtió; ``error`` contiene
    la causa. ``updated_tables`` carries the per-table row counts
    even on failure (the dict reflects what was rolled back).
    """

    success: bool
    old_chip: str
    new_chip: str
    updated_tables: dict[str, int] = field(default_factory=dict)
    error: str | None = None


__all__ = ["ChangeChipResult"]
