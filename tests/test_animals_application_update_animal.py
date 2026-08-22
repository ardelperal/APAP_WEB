"""Application-layer tests for ``update_animal`` (slice #420-7 fourth surface).

Mirrors the stub-port pattern from
``tests/test_animals_application_get_animal_by_nchip.py``,
``tests/test_animals_application_list_animals.py`` and
``tests/test_animals_application_create_animal.py`` so the use-case
tests stay transport-free: the application code never sees
``InsForgeClient`` or ``SqlExecutor``; it talks to the
:class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

import pytest

from app.modules.animals.application.update_animal import (
    AnimalUpdateValidationError,
    update_animal,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self) -> None:
        self.last_animal_id: str | None = None
        self.last_nombre: str | None = None
        self.last_especie: Especie | None = None
        self.last_sexo: Sexo | None = None
        self.last_fnacimiento: str | None = None
        self.next_animal: Animal | None = None
        self.next_missing: bool = False

    def update_animal(
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        fnacimiento: str | None = None,
    ) -> Animal | None:
        self.last_animal_id = animal_id
        self.last_nombre = nombre
        self.last_especie = especie
        self.last_sexo = sexo
        self.last_fnacimiento = fnacimiento
        if self.next_missing:
            return None
        if self.next_animal is None:
            raise AssertionError(
                "stub next_animal unset; set it in the test before "
                "calling update_animal"
            )
        return self.next_animal

    # No-op stubs for the other Protocol methods so the runtime
    # check on ``runtime_checkable`` does not trip if the stub is
    # incidentally validated elsewhere.
    def get_animal_by_nchip(self, nchip: str) -> Animal | None:  # pragma: no cover
        return None

    def list_animals(  # pragma: no cover
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activo_only: bool = True,
    ) -> list[Animal]:
        return []

    def create_animal(  # pragma: no cover
        self,
        *,
        nchip: str,
        nombre: str,
        especie: Especie,
        sexo: Sexo,
        fnacimiento: str,
    ) -> Animal:
        raise NotImplementedError


def _animal() -> Animal:
    return Animal(
        id="00000000-0000-0000-0000-000000000042",
        NCHIP="941000000012345",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
    )


def test_happy_path_partial_update_strips_and_delegates() -> None:
    """Partial update: only ``nombre`` changes; the rest stay untouched."""
    port = _StubPort()
    port.next_animal = _animal()

    result = update_animal(
        port,
        animal_id="00000000-0000-0000-0000-000000000042",
        nombre=" Luna v2 ",
        especie=None,
        sexo=None,
        fnacimiento=None,
    )

    assert result is port.next_animal
    assert port.last_animal_id == "00000000-0000-0000-0000-000000000042"
    assert port.last_nombre == "Luna v2"
    assert port.last_especie is None
    assert port.last_sexo is None
    assert port.last_fnacimiento is None


def test_all_fields_pass_through_unchanged() -> None:
    """Full update: every kwarg reaches the port with the same value."""
    port = _StubPort()
    port.next_animal = _animal()

    update_animal(
        port,
        animal_id="id",
        nombre="NewName",
        especie=Especie.FELINA,
        sexo=Sexo.M,
        fnacimiento="2025-01-01",
    )

    assert port.last_nombre == "NewName"
    assert port.last_especie is Especie.FELINA
    assert port.last_sexo is Sexo.M
    assert port.last_fnacimiento == "2025-01-01"


def test_blank_nombre_raises_before_touching_port() -> None:
    """A blank ``nombre`` short-circuits before the port sees anything."""
    port = _StubPort()
    port.next_animal = _animal()

    for blank in ("", "   ", "\t"):
        with pytest.raises(AnimalUpdateValidationError, match="vacio"):
            update_animal(port, animal_id="id", nombre=blank)

    assert port.last_nombre is None


def test_none_kwargs_pass_through_unchanged() -> None:
    """``None`` kwargs are forwarded to the port — the no-op branch lives there."""
    port = _StubPort()
    port.next_animal = _animal()

    update_animal(port, animal_id="id")

    assert port.last_nombre is None
    assert port.last_especie is None
    assert port.last_sexo is None
    assert port.last_fnacimiento is None


def test_missing_id_returns_none() -> None:
    """A non-existent id propagates ``None`` up — the route handler reads it as 404."""
    port = _StubPort()
    port.next_missing = True

    result = update_animal(
        port,
        animal_id="missing",
        nombre="Doesn't matter",
    )

    assert result is None


def test_validation_error_subclasses_value_error() -> None:
    """Existing ``except ValueError`` clauses in legacy callers keep working."""
    assert issubclass(AnimalUpdateValidationError, ValueError)
