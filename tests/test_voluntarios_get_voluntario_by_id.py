"""TDD tests: get_voluntario_by_id use case (epic #420 PR-A).

Covers:
- Found: returns Voluntario.
- Not found: returns None.
- Blank id: raises VoluntarioValidationError.
- None id: raises VoluntarioValidationError.
"""
from __future__ import annotations

import pytest

from app.modules.voluntarios.application.get_voluntario_by_id import (
    VoluntarioValidationError,
    get_voluntario_by_id,
)
from app.modules.voluntarios.domain.voluntario import Voluntario


class _FakeVoluntariosPort:
    __slots__ = ("_row",)

    def __init__(self, row: Voluntario | None) -> None:
        self._row = row

    def get_voluntario_by_id(self, voluntario_id: str) -> Voluntario | None:
        return self._row


class TestGetVoluntarioById:
    def test_found_returns_voluntario(self) -> None:
        volunteer = Voluntario(
            id="11111111-1111-1111-1111-111111111111",
            voluntario="Ana Garcia",
            activo=True,
        )
        port = _FakeVoluntariosPort(volunteer)
        result = get_voluntario_by_id(port, "11111111-1111-1111-1111-111111111111")  # type: ignore[arg-type]
        assert result is volunteer

    def test_not_found_returns_none(self) -> None:
        port = _FakeVoluntariosPort(None)
        assert get_voluntario_by_id(port, "11111111-1111-1111-1111-111111111111") is None  # type: ignore[arg-type]


class TestGetVoluntarioByIdValidation:
    @pytest.mark.parametrize("voluntario_id", ["", "   "])
    def test_blank_id_raises(self, voluntario_id: str) -> None:
        port = _FakeVoluntariosPort(None)
        with pytest.raises(VoluntarioValidationError):
            get_voluntario_by_id(port, voluntario_id)  # type: ignore[arg-type]

    def test_none_id_raises(self) -> None:
        port = _FakeVoluntariosPort(None)
        with pytest.raises(VoluntarioValidationError):
            get_voluntario_by_id(port, None)  # type: ignore[arg-type]
