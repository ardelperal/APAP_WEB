"""Application-layer tests for primary-key animal lookup."""
from __future__ import annotations

import pytest

from app.modules.animals.application.get_animal_by_id import get_animal_by_id
from app.modules.animals.domain.animal import Animal, Especie, Sexo


class _StubPort:
    """Record primary-key lookup calls without transport I/O."""

    def __init__(self, animal: Animal | None) -> None:
        self._animal = animal
        self.calls: list[str] = []

    def get_animal_by_id(self, animal_id: str) -> Animal | None:
        self.calls.append(animal_id)
        return self._animal


@pytest.mark.parametrize("animal_id", ["", "   "])
def test_blank_animal_id_raises_value_error(animal_id: str) -> None:
    port = _StubPort(animal=None)

    with pytest.raises(ValueError, match="animal_id is required"):
        get_animal_by_id(port, animal_id)  # type: ignore[arg-type]

    assert port.calls == [], "invalid input must not touch the port"


def test_whitespace_is_stripped_and_delegated() -> None:
    expected = Animal(
        id="animal-1",
        NCHIP="941000000000001",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
    )
    port = _StubPort(animal=expected)

    result = get_animal_by_id(port, " animal-1 ")  # type: ignore[arg-type]

    assert result is expected, "use case must return the port result unchanged"
    assert port.calls == ["animal-1"], "use case must strip before delegation"
