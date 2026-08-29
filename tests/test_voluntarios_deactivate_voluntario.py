"""TDD tests: deactivate_voluntario use case (epic #420 PR-A).

Covers:
- Active volunteer: returns True.
- Already inactive: returns False.
- Non-existent: returns False (idempotent).
- Blank id: raises VoluntarioValidationError.
"""
from __future__ import annotations

import pytest

from app.modules.voluntarios.application.deactivate_voluntario import (
    VoluntarioValidationError,
    deactivate_voluntario,
)


class _FakeVoluntariosPort:
    __slots__ = ("_result",)

    def __init__(self, result: bool) -> None:
        self._result = result

    def deactivate_voluntario(self, voluntario_id: str) -> bool:
        return self._result


class TestDeactivateVoluntario:
    def test_active_volunteer_returns_true(self) -> None:
        port = _FakeVoluntariosPort(True)
        assert deactivate_voluntario(port, "11111111-1111-1111-1111-111111111111") is True  # type: ignore[arg-type]

    def test_inactive_voluntario_returns_false(self) -> None:
        port = _FakeVoluntariosPort(False)
        assert deactivate_voluntario(port, "11111111-1111-1111-1111-111111111111") is False  # type: ignore[arg-type]


class TestDeactivateVoluntarioValidation:
    @pytest.mark.parametrize("voluntario_id", ["", "   "])
    def test_blank_id_raises(self, voluntario_id: str) -> None:
        port = _FakeVoluntariosPort(True)
        with pytest.raises(VoluntarioValidationError):
            deactivate_voluntario(port, voluntario_id)  # type: ignore[arg-type]

    def test_none_id_raises(self) -> None:
        port = _FakeVoluntariosPort(True)
        with pytest.raises(VoluntarioValidationError):
            deactivate_voluntario(port, None)  # type: ignore[arg-type]
