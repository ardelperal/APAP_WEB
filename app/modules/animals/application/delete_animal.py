"""Use case: soft-delete an animal.

Slice #420-7 fifth surface (joins get_animal_by_nchip #587,
list_animals #596, create_animal #597 and update_animal #603).
The single application-layer entry point for hexagonal animal
deactivation. Delegates to
:class:`~app.modules.animals.ports.AnimalsPort` so the application
code stays transport-agnostic (AGENTS.md §31) — no FastAPI, no
LocalBackend, no Jinja in this file.

The use case strips whitespace from ``animal_id`` and rejects
empty strings before delegation — a malformed id would surface as
a 500 from the adapter (postgres syntax error on an empty UUID)
otherwise. ``None``-shape input is also rejected for the same
reason.
"""
from __future__ import annotations

from app.modules.animals.domain.animal import Animal
from app.modules.animals.ports.animals_port import AnimalsPort


class AnimalDeleteValidationError(ValueError):
    """Raised when ``animal_id`` fails the domain-validation rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it.
    """


def _require_animal_id(animal_id: str | None) -> str:
    if animal_id is None:
        raise AnimalDeleteValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "animal_id es obligatorio"
        )
    stripped = animal_id.strip()
    if not stripped:
        raise AnimalDeleteValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "animal_id es obligatorio y no puede estar vacio"
        )
    return stripped


def delete_animal(
    animals_port: AnimalsPort,
    animal_id: str,
) -> Animal | None:
    """Soft-delete the animal with ``animal_id`` and return the row.

    Idempotent: a second call on an already-inactive animal returns
    the same row (``activo=False`` either way). Returns ``None``
    when ``animal_id`` does not exist.
    """
    clean_id = _require_animal_id(animal_id)
    return animals_port.delete_animal(clean_id)


__all__ = ["delete_animal", "AnimalDeleteValidationError"]
