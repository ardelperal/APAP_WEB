"""Domain tests for the animals slice (slice-completeness gate)."""
from __future__ import annotations

from app.modules.animals.domain.animal import Animal, Especie, Sexo


def test_animal_dataclass_carries_business_key() -> None:
    """The dataclass exposes NCHIP as the join key per feature-01."""
    animal = Animal(
        id="00000000-0000-0000-0000-000000000001",
        NCHIP="941000000012345",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
    )
    assert animal.NCHIP == "941000000012345"
    assert animal.activo is True


def test_especie_sexo_enums_are_stable() -> None:
    """The enum values must match the legacy ``TbFichaAnimal`` codes."""
    assert Especie.CANINA.value == "CANINA"
    assert Especie.FELINA.value == "FELINA"
    assert Sexo.M.value == "M"
    assert Sexo.H.value == "H"