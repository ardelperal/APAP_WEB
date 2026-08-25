"""Application-layer tests for ``create_animal`` (slice #420-7 third surface).

Mirrors the stub-port pattern from
``tests/test_animals_application_get_animal_by_nchip.py`` and
``tests/test_animals_application_list_animals.py`` so the use-case
tests stay transport-free: the application code never sees
``InsForgeClient`` or ``SqlExecutor``; it talks to the
:class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

import pytest

from app.modules.animals.application.create_animal import (
    AnimalValidationError,
    create_animal,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self) -> None:
        self.last_nchip: str | None = None
        self.last_nombre: str | None = None
        self.last_especie: Especie | None = None
        self.last_sexo: Sexo | None = None
        self.last_fnacimiento: str | None = None
        self.last_optional_fields: dict[str, str | None] = {}
        self.next_animal: Animal | None = None

    def create_animal(
        self,
        *,
        nchip: str,
        nombre: str,
        especie: Especie,
        sexo: Sexo,
        fnacimiento: str,
        **optional_fields: str | None,
    ) -> Animal:
        self.last_nchip = nchip
        self.last_nombre = nombre
        self.last_especie = especie
        self.last_sexo = sexo
        self.last_fnacimiento = fnacimiento
        self.last_optional_fields = optional_fields
        if self.next_animal is None:
            raise AssertionError(
                "stub next_animal unset; set it in the test before "
                "calling create_animal"
            )
        return self.next_animal

    # Provide no-op stubs for the other Protocol methods so the
    # runtime check on ``runtime_checkable`` does not trip if the
    # stub is incidentally validated elsewhere.
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


def _animal() -> Animal:
    return Animal(
        id="00000000-0000-0000-0000-000000000042",
        NCHIP="941000000012345",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
    )


def test_happy_path_strips_inputs_and_delegates() -> None:
    """Valid inputs are stripped and forwarded verbatim to the port."""
    port = _StubPort()
    port.next_animal = _animal()

    result = create_animal(
        port,
        nchip=" 941000000012345 ",
        nombre=" Luna ",
        especie=Especie.CANINA,
        sexo=Sexo.H,
        fnacimiento="2024-03-01",
    )

    assert result is port.next_animal
    assert port.last_nchip == "941000000012345"
    assert port.last_nombre == "Luna"
    assert port.last_especie is Especie.CANINA
    assert port.last_sexo is Sexo.H
    assert port.last_fnacimiento == "2024-03-01"


def test_blank_nchip_raises_before_touching_port() -> None:
    """A blank ``nchip`` short-circuits before the port sees anything."""
    port = _StubPort()
    port.next_animal = _animal()

    for blank in ("", "   ", "\t"):
        with pytest.raises(AnimalValidationError, match="NCHIP"):
            create_animal(
                port,
                nchip=blank,
                nombre="Luna",
                especie=Especie.CANINA,
                sexo=Sexo.H,
                fnacimiento="2024-03-01",
            )

    assert port.last_nchip is None


def test_blank_nombre_raises_before_touching_port() -> None:
    """A blank ``nombre`` short-circuits before the port sees anything."""
    port = _StubPort()
    port.next_animal = _animal()

    with pytest.raises(AnimalValidationError, match="NombreAnimal"):
        create_animal(
            port,
            nchip="941000000012345",
            nombre="",
            especie=Especie.CANINA,
            sexo=Sexo.H,
            fnacimiento="2024-03-01",
        )

    assert port.last_nombre is None


def test_validation_error_subclasses_value_error() -> None:
    """Existing ``except ValueError`` clauses in legacy callers keep working."""
    assert issubclass(AnimalValidationError, ValueError)


def test_especie_and_sexo_pass_through() -> None:
    """Enum values flow through unchanged — the dataclass-level type
    check is the only validation needed for the two enums."""
    port = _StubPort()
    port.next_animal = _animal()

    create_animal(
        port,
        nchip="941000000012345",
        nombre="Luna",
        especie=Especie.FELINA,
        sexo=Sexo.M,
        fnacimiento="2024-03-01",
    )

    assert port.last_especie is Especie.FELINA
    assert port.last_sexo is Sexo.M


def test_optional_fields_pass_through_to_port() -> None:
    """The widened writable fields reach the port unchanged."""
    port = _StubPort()
    port.next_animal = _animal()

    create_animal(
        port,
        nchip="941000000012345",
        nombre="Luna",
        especie=Especie.CANINA,
        sexo=Sexo.H,
        fnacimiento="2024-03-01",
        Raza="Labrador",
        Observaciones="Friendly",
    )

    assert port.last_optional_fields["Raza"] == "Labrador", (
        "create must delegate the optional breed"
    )
    assert port.last_optional_fields["Observaciones"] == "Friendly", (
        "create must delegate optional observations"
    )
