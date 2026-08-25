"""Domain tests for the animals slice (slice-completeness gate)."""
from __future__ import annotations

from dataclasses import fields
from typing import get_type_hints

from app.modules.animals.domain.animal import Animal, Especie, Sexo

_OPTIONAL_FIELDS = (
    "fecha_alta",
    "estado",
    "TraeNChip",
    "FIMPLANTACIONCHIP",
    "Raza",
    "Color",
    "Pelo",
    "Tamano",
    "Caracter",
    "FDefuncion",
    "Terapia",
    "Observaciones",
    "NombreFoto",
    "Cartilla",
    "Eutanasia",
    "RazaPPP",
    "Mestizo",
    "EutanasiaOtrasCausas",
    "EutanasiaEnfermedad",
    "UltimoEstadoAntesDeFallecido",
    "ComunicacionARIAC",
)


def _minimal_animal() -> Animal:
    return Animal(
        id="00000000-0000-0000-0000-000000000001",
        NCHIP="941000000012345",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
    )


def test_animal_dataclass_carries_business_key() -> None:
    """The dataclass exposes NCHIP as the join key per feature-01."""
    animal = _minimal_animal()
    assert animal.NCHIP == "941000000012345", "NCHIP must remain the business key"
    assert animal.activo is True, "activo must retain its default"


def test_animal_dataclass_has_the_28_field_read_shape() -> None:
    expected = (
        "id", "NCHIP", "NombreAnimal", "Especie", "Sexo", "FNacimiento",
        "activo", *_OPTIONAL_FIELDS,
    )
    assert tuple(field.name for field in fields(Animal)) == expected, (
        "Animal must expose the seven original fields followed by the 21 widened fields"
    )
    hints = get_type_hints(Animal)
    for name in _OPTIONAL_FIELDS:
        assert hints[name] == str | None, f"{name} must be typed as str | None"


def test_animal_minimal_constructor_defaults_every_widened_field() -> None:
    animal = _minimal_animal()
    for name in _OPTIONAL_FIELDS:
        assert getattr(animal, name) is None, f"{name} must default to None"


def test_especie_sexo_enums_are_stable() -> None:
    """The enum values must match the legacy ``TbFichaAnimal`` codes."""
    assert Especie.CANINA.value == "CANINA", "CANINA must match the legacy code"
    assert Especie.FELINA.value == "FELINA", "FELINA must match the legacy code"
    assert Sexo.M.value == "M", "M must match the legacy code"
    assert Sexo.H.value == "H", "H must match the legacy code"
