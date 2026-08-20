"""Application-layer tests for the animals slice."""
from __future__ import annotations

from app.modules.animals.application.get_animal_by_nchip import (
    get_animal_by_nchip,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self, animal: Animal | None) -> None:
        self._animal = animal
        self.last_nchip: str | None = None

    def get_animal_by_nchip(self, nchip: str) -> Animal | None:
        self.last_nchip = nchip
        return self._animal


def test_empty_nchip_short_circuits_without_touching_port() -> None:
    """Empty / whitespace NCHIP short-circuits without calling the port."""
    port = _StubPort(animal=None)
    assert get_animal_by_nchip(port, "") is None
    assert get_animal_by_nchip(port, "   ") is None
    assert port.last_nchip is None


def test_non_empty_nchip_is_stripped_and_delegated() -> None:
    """Non-empty NCHIP is stripped and passed to the port."""
    expected = Animal(
        id="00000000-0000-0000-0000-000000000001",
        NCHIP="941000000012345",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
    )
    port = _StubPort(animal=expected)
    result = get_animal_by_nchip(port, " 941000000012345 ")
    assert result is expected
    assert port.last_nchip == "941000000012345"
