"""Use case: change the animal's chip and propagate the new value.

Slice #420-7 eighth surface (joins get_animal_by_nchip #587,
list_animals #596, create_animal #597, update_animal #603,
delete_animal #604, record_lifecycle_event #609 and
list_lifecycle_events #610). The single application-layer entry
point for hexagonal chip cascading. Delegates to
:class:`~app.modules.animals.ports.AnimalsPort` so the application
code stays transport-agnostic (AGENTS.md §31) — no FastAPI, no
LocalBackend, no Jinja in this file.

The use case enforces the two pre-flight invariants the legacy
``chip_service.change_animal_chip`` did in addition to the
adapter-side uniqueness check:

- ``new_chip`` must be non-blank AND different from ``old_chip``
  (changing a chip to its current value is a no-op the legacy
  rejects so the operator notices the mistake).
- ``reason`` must be non-blank (the audit trail needs a
  non-trivial human justification; blank would let a typo land a
  meaningless CHIP_CHANGED event in the timeline).

The remaining checks (uniqueness of ``new_chip``; current chip
matches ``old_chip``; per-table UPDATE success) live in the
adapter because they need the transport / DB. The use case only
validates inputs that are independent of the backend.
"""
from __future__ import annotations

from app.modules.animals.domain.change_chip_result import ChangeChipResult
from app.modules.animals.ports.animals_port import AnimalsPort


class ChipCascadeValidationError(ValueError):
    """Raised when ``new_chip`` or ``reason`` fails the domain-validation rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it.
    """


def _require_non_blank(value: str | None, field_name: str) -> str:
    if value is None:
        raise ChipCascadeValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"{field_name} es obligatorio"
        )
    stripped = value.strip()
    if not stripped:
        raise ChipCascadeValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"{field_name} es obligatorio y no puede estar vacio"
        )
    return stripped


def change_animal_chip(
    animals_port: AnimalsPort,
    *,
    animal_id: str,
    old_chip: str,
    new_chip: str,
    reason: str,
    operador_user_id: str,
) -> ChangeChipResult:
    """Change the animal's chip and propagate across the 6 dependent tables.

    Returns the saga result. ``success=False`` indicates the adapter
    rolled back; ``error`` carries the cause for the route handler
    to translate into the appropriate HTTP code.
    """
    clean_animal_id = _require_non_blank(animal_id, "animal_id")
    clean_new_chip = _require_non_blank(new_chip, "new_chip")
    clean_reason = _require_non_blank(reason, "reason")
    if clean_new_chip == old_chip:
        raise ChipCascadeValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "new_chip no puede ser igual a old_chip"
        )

    return animals_port.change_animal_chip(
        animal_id=clean_animal_id,
        old_chip=old_chip,
        new_chip=clean_new_chip,
        reason=clean_reason,
        operador_user_id=operador_user_id,
    )


__all__ = ["change_animal_chip", "ChipCascadeValidationError"]
