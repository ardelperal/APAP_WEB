"""Application-layer tests for ``delete_animal`` (slice #420-7 fifth surface).

Mirrors the stub-port pattern from the previous application-layer
tests in this slice so the use-case stays transport-free: the
application code never sees ``InsForgeClient`` or ``SqlExecutor``;
it talks to the :class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

import pytest

from app.modules.animals.application.delete_animal import (
    AnimalDeleteValidationError,
    delete_animal,
)
from app.modules.animals.domain.animal import Animal, Especie, Sexo


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self) -> None:
        self.last_animal_id: str | None = None
        self.next_animal: Animal | None = None
        self.next_missing: bool = False

    def delete_animal(self, animal_id: str) -> Animal | None:
        self.last_animal_id = animal_id
        if self.next_missing:
            return None
        if self.next_animal is None:
            raise AssertionError(
                "stub next_animal unset; set it in the test before "
                "calling delete_animal"
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

    def update_animal(  # pragma: no cover
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: Especie | None = None,
        sexo: Sexo | None = None,
        fnacimiento: str | None = None,
    ) -> Animal | None:
        raise NotImplementedError


def _animal(*, activo: bool = False) -> Animal:
    """Build a minimal ``Animal`` for the test — ``activo=False`` by
    default because the delete branch returns a deactivated row."""
    return Animal(
        id="00000000-0000-0000-0000-000000000042",
        NCHIP="941000000012345",
        NombreAnimal="Luna",
        Especie=Especie.CANINA,
        Sexo=Sexo.H,
        FNacimiento="2024-03-01",
        activo=activo,
    )


def test_happy_path_strips_and_delegates() -> None:
    """Valid id is stripped and forwarded verbatim to the port."""
    port = _StubPort()
    port.next_animal = _animal()

    result = delete_animal(port, animal_id=" id-with-spaces ")

    assert result is port.next_animal
    assert port.last_animal_id == "id-with-spaces"


def test_missing_id_returns_none() -> None:
    """A non-existent id propagates ``None`` — the route reads it as 404."""
    port = _StubPort()
    port.next_missing = True

    result = delete_animal(port, animal_id="missing")

    assert result is None
    assert port.last_animal_id == "missing"


def test_blank_id_raises_before_touching_port() -> None:
    """Blank / whitespace-only ids short-circuit before the port sees anything."""
    port = _StubPort()

    for blank in ("", "   ", "\t\n"):
        with pytest.raises(AnimalDeleteValidationError, match="animal_id"):
            delete_animal(port, animal_id=blank)

    assert port.last_animal_id is None


def test_none_id_raises() -> None:
    """``None`` (defensive — the type system catches this, but pin the contract)."""
    port = _StubPort()

    with pytest.raises(AnimalDeleteValidationError, match="animal_id"):
        delete_animal(port, animal_id=None)  # type: ignore[arg-type]

    assert port.last_animal_id is None


def test_validation_error_subclasses_value_error() -> None:
    """Existing ``except ValueError`` clauses in legacy callers keep working."""
    assert issubclass(AnimalDeleteValidationError, ValueError)


def test_idempotent_second_call_returns_same_row() -> None:
    """A second call on an already-inactive animal still returns the row.

    The adapter's ``UPDATE ... SET activo = FALSE`` is a no-op when
    the row is already inactive; the port returns the row either
    way. The test pins that the use case does not reject the
    already-deactivated row at the application layer.
    """
    port = _StubPort()
    port.next_animal = _animal(activo=False)

    result = delete_animal(port, animal_id="id")

    assert result is port.next_animal
    assert result is not None
    assert result.activo is False
