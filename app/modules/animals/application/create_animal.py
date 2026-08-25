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
contract. The complete writable column set is delegated unchanged after
required-field validation.
"""
# ruff: noqa: N803 — kwargs intentionally preserve legacy schema column names
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


def create_animal(  # noqa: N803, PLR0913  # schema-named fields mirror the 24-column AnimalForm contract
    animals_port: AnimalsPort,
    *,
    nchip: str,
    nombre: str,
    especie: Especie,
    sexo: Sexo,
    fnacimiento: str,
    TraeNChip: str | None = None,
    FIMPLANTACIONCHIP: str | None = None,
    Raza: str | None = None,
    Color: str | None = None,
    Pelo: str | None = None,
    Tamano: str | None = None,
    Caracter: str | None = None,
    FDefuncion: str | None = None,
    Terapia: str | None = None,
    Observaciones: str | None = None,
    NombreFoto: str | None = None,
    Cartilla: str | None = None,
    Eutanasia: str | None = None,
    RazaPPP: str | None = None,
    Mestizo: str | None = None,
    EutanasiaOtrasCausas: str | None = None,
    EutanasiaEnfermedad: str | None = None,
    UltimoEstadoAntesDeFallecido: str | None = None,
    ComunicacionARIAC: str | None = None,
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
        TraeNChip=TraeNChip,
        FIMPLANTACIONCHIP=FIMPLANTACIONCHIP,
        Raza=Raza,
        Color=Color,
        Pelo=Pelo,
        Tamano=Tamano,
        Caracter=Caracter,
        FDefuncion=FDefuncion,
        Terapia=Terapia,
        Observaciones=Observaciones,
        NombreFoto=NombreFoto,
        Cartilla=Cartilla,
        Eutanasia=Eutanasia,
        RazaPPP=RazaPPP,
        Mestizo=Mestizo,
        EutanasiaOtrasCausas=EutanasiaOtrasCausas,
        EutanasiaEnfermedad=EutanasiaEnfermedad,
        UltimoEstadoAntesDeFallecido=UltimoEstadoAntesDeFallecido,
        ComunicacionARIAC=ComunicacionARIAC,
    )


__all__ = ["create_animal", "AnimalValidationError"]
