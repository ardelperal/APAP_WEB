"""Use case: create a new animal.

Slice #420-7 third surface (joins ``get_animal_by_nchip`` #587 and
``list_animals`` #596). The single application-layer entry point
for hexagonal animal creation. Delegates to
:class:`~app.modules.animals.ports.AnimalsPort` so the application
code stays transport-agnostic (AGENTS.md §31) — no FastAPI, no
InsForge, no Jinja in this file.

The use case enforces the same domain-validation rules the legacy
``app.modules.animals.service._validate_required_fields`` did for
``create_animal``: NCHIP and NombreAnimal are mandatory and must
be non-blank; Especie and Sexo must match the enum. The hexagonal
dataclass enforces the enum constraint via the StrEnum constructor
so the only thing the use case has to check is the string-blank
contract. The legacy's richer column set (Raza, Color, Pelo, etc.)
is out of scope — the port's signature is the round-trip fields
the hexagonal ``Animal`` already encodes.
"""
from __future__ import annotations

from app.modules.animals.domain.animal import Animal, Especie, Sexo
from app.modules.animals.ports.animals_port import AnimalsPort


class AnimalValidationError(ValueError):
    """Raised when the inputs fail the domain-validation rules.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in legacy callers keep catching it. The hexagonal
    signature carries the raised-into-context information as the
    string message so the route layer can surface the message to
    the operator verbatim.
    """


def _require_non_blank(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise AnimalValidationError(  # noqa: TRY003 — operator-facing diagnostic
            f"{field_name} es obligatorio y no puede estar vacio"
        )
    return stripped


def create_animal(
    animals_port: AnimalsPort,
    *,
    nchip: str,
    nombre: str,
    especie: Especie,
    sexo: Sexo,
    fnacimiento: str,
) -> Animal:
    """Create a new animal and return the persisted row.

    Validates the four string/enum inputs and delegates to the port.
    The adapter is responsible for primary-key generation and for
    raising :class:`app.core.data_access.UniqueViolation` when the
    NCHIP already exists; this wrapper does no DB work.
    """
    clean_nchip = _require_non_blank(nchip, "NCHIP")
    clean_nombre = _require_non_blank(nombre, "NombreAnimal")

    return animals_port.create_animal(
        nchip=clean_nchip,
        nombre=clean_nombre,
        especie=especie,
        sexo=sexo,
        fnacimiento=fnacimiento,
    )


__all__ = ["create_animal", "AnimalValidationError"]
