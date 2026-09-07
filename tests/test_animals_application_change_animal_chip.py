"""Application-layer tests for ``change_animal_chip`` (slice #420-7 eighth surface).

Mirrors the stub-port pattern from the previous application-layer
tests in this slice so the use-case stays transport-free: the
application code never sees ``LocalPostgresExecutor`` or ``SqlExecutor``;
it talks to the :class:`AnimalsPort` Protocol only.
"""
from __future__ import annotations

import pytest

from app.modules.animals.application.change_animal_chip import (
    ChipCascadeValidationError,
    change_animal_chip,
)
from app.modules.animals.domain.change_chip_result import ChangeChipResult


class _StubPort:
    """Stub implementation of :class:`AnimalsPort` for unit tests."""

    def __init__(self) -> None:
        self.last_animal_id: str | None = None
        self.last_old_chip: str | None = None
        self.last_new_chip: str | None = None
        self.last_reason: str | None = None
        self.last_operador_user_id: str | None = None
        self.next_result: ChangeChipResult | None = None

    def change_animal_chip(
        self,
        *,
        animal_id: str,
        old_chip: str,
        new_chip: str,
        reason: str,
        operador_user_id: str,
    ) -> ChangeChipResult:
        self.last_animal_id = animal_id
        self.last_old_chip = old_chip
        self.last_new_chip = new_chip
        self.last_reason = reason
        self.last_operador_user_id = operador_user_id
        if self.next_result is None:
            raise AssertionError(
                "stub next_result unset; set it in the test before "
                "calling change_animal_chip"
            )
        return self.next_result

    # No-op stubs for the other Protocol methods so the runtime
    # check on ``runtime_checkable`` does not trip if the stub is
    # incidentally validated elsewhere.
    def get_animal_by_nchip(self, nchip: str) -> object:  # pragma: no cover
        return None

    def list_animals(  # pragma: no cover
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        activo_only: bool = True,
    ) -> list[object]:
        return []

    def create_animal(  # pragma: no cover
        self,
        *,
        nchip: str,
        nombre: str,
        especie: object,
        sexo: object,
        fnacimiento: str,
    ) -> object:
        raise NotImplementedError

    def update_animal(  # pragma: no cover
        self,
        animal_id: str,
        *,
        nombre: str | None = None,
        especie: object | None = None,
        sexo: object | None = None,
        fnacimiento: str | None = None,
    ) -> object | None:
        raise NotImplementedError

    def delete_animal(self, animal_id: str) -> object | None:  # pragma: no cover
        return None

    def record_lifecycle_event(  # pragma: no cover
        self,
        *,
        animal_id: str,
        event_type: object,
        event_timestamp: object,
        created_by: str,
        caused_by_event_id: str | None = None,
        source_entity_type: str | None = None,
        source_entity_id: str | None = None,
        legacy_source_table: str | None = None,
        legacy_source_id: int | None = None,
        metadata: dict | None = None,
    ) -> object:
        raise NotImplementedError

    def list_lifecycle_events(  # pragma: no cover
        self,
        animal_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        event_types: list[object] | None = None,
    ) -> list[object]:
        return []


def _result(success: bool = True) -> ChangeChipResult:
    return ChangeChipResult(
        success=success,
        old_chip="941000000000001",
        new_chip="941000000099999",
        updated_tables={
            "animals": 1,
            "entradas": 3,
            "acogidas": 1,
            "adopciones": 0,
            "actuaciones_sanitarias": 5,
            "terapias": 0,
        },
        error=None if success else "boom",
    )


def test_happy_path_strips_and_delegates() -> None:
    """Valid kwargs are stripped and forwarded verbatim to the port."""
    port = _StubPort()
    port.next_result = _result()

    result = change_animal_chip(
        port,
        animal_id=" animal-id ",
        old_chip="941000000000001",
        new_chip=" 941000000099999 ",
        reason=" chip reimplanted ",
        operador_user_id="operator@apap.local",
    )

    assert result is port.next_result
    assert port.last_animal_id == "animal-id"
    assert port.last_old_chip == "941000000000001"
    assert port.last_new_chip == "941000000099999"
    assert port.last_reason == "chip reimplanted"
    assert port.last_operador_user_id == "operator@apap.local"


def test_blank_new_chip_raises_before_touching_port() -> None:
    """A blank ``new_chip`` short-circuits before the port sees anything."""
    port = _StubPort()

    for blank in ("", "   ", "\t"):
        with pytest.raises(ChipCascadeValidationError, match="new_chip"):
            change_animal_chip(
                port,
                animal_id="animal-id",
                old_chip="941000000000001",
                new_chip=blank,
                reason="any reason",
                operador_user_id="operator@apap.local",
            )

    assert port.last_new_chip is None


def test_blank_reason_raises_before_touching_port() -> None:
    """A blank ``reason`` short-circuits before the port sees anything."""
    port = _StubPort()

    with pytest.raises(ChipCascadeValidationError, match="reason"):
        change_animal_chip(
            port,
            animal_id="animal-id",
            old_chip="941000000000001",
            new_chip="941000000099999",
            reason="",
            operador_user_id="operator@apap.local",
        )

    assert port.last_reason is None


def test_same_chip_raises() -> None:
    """``new_chip == old_chip`` is a no-op the legacy rejects — raise before
    delegating so the operator notices the typo."""
    port = _StubPort()

    with pytest.raises(ChipCascadeValidationError, match="new_chip"):
        change_animal_chip(
            port,
            animal_id="animal-id",
            old_chip="941000000000001",
            new_chip="941000000000001",
            reason="no-op",
            operador_user_id="operator@apap.local",
        )

    assert port.last_new_chip is None


def test_success_false_propagates() -> None:
    """``success=False`` flows through the use case unchanged — the route
    handler reads the error field for the HTTP code mapping."""
    port = _StubPort()
    port.next_result = _result(success=False)

    result = change_animal_chip(
        port,
        animal_id="animal-id",
        old_chip="941000000000001",
        new_chip="941000000099999",
        reason="reimplant",
        operador_user_id="operator@apap.local",
    )

    assert result is port.next_result
    assert result.success is False
    assert result.error == "boom"


def test_validation_error_subclasses_value_error() -> None:
    """Existing ``except ValueError`` clauses in legacy callers keep working."""
    assert issubclass(ChipCascadeValidationError, ValueError)
