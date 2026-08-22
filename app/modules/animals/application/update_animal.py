"""Use case: update an existing animal.

Slice #420-7 fourth surface (joins get_animal_by_nchip #587,
list_animals #596 and create_animal #597). The single
application-layer entry point for hexagonal animal updates.
Delegates to :class:`~app.modules.animals.ports.AnimalsPort` so
the application code stays transport-agnostic (AGENTS.md §31) — no
FastAPI, no InsForge, no Jinja in this file.

All update kwargs are optional. Passing ``None`` (or omitting) for a
field leaves it untouched on the DB side; the use case strips
``nombre`` before delegation so a whitespace-only string still
raises the validation error rather than writing ``"   "`` to the
row. The two enum fields (``Especie``, ``Sexo``) go through the
StrEnum constructor unchanged — invalid values raise ``ValueError``
in the adapter, which the application layer lets propagate so the
route handler translates it into a 422.
"""
from __future__ import annotations

from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.ports.animals_port import AnimalsPort


class AnimalUpdateValidationError(ValueError):
    """Raised when an update input fails the domain-validation rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it.
    """


def _optional_non_blank(value: str | None) -> str | None:
    """Strip ``value`` if present; raise on whitespace-only.

    ``None`` passes through (the field is skipped on the DB side).
    Empty / whitespace strings raise — the legacy
    ``_validate_required_fields`` rejects the same shape, and the
    hexagonal path keeps the contract.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise AnimalUpdateValidationError(  # noqa: TRY003 — operator-facing diagnostic
            "el valor del campo no puede estar vacio"
        )
    return stripped


def update_animal(
    animals_port: AnimalsPort,
    animal_id: str,
    *,
    nombre: str | None = None,
    especie: Especie | None = None,
    sexo: Sexo | None = None,
    fnacimiento: str | None = None,
) -> Animal | None:
    """Update the named fields of ``animal_id``; return the new row.

    Returns ``None`` when ``animal_id`` does not exist; returns the
    updated :class:`Animal` otherwise. The adapter handles the SQL
    UPDATE ... RETURNING that produces the response shape.
    """
    clean_nombre = _optional_non_blank(nombre)

    return animals_port.update_animal(
        animal_id=animal_id,
        nombre=clean_nombre,
        especie=especie,
        sexo=sexo,
        fnacimiento=fnacimiento,
    )


__all__ = ["update_animal", "AnimalUpdateValidationError"]
