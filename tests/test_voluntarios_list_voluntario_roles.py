"""TDD tests: list_voluntario_roles use case (epic #420 PR-A).

Covers:
- Happy path: returns sorted list of role strings.
- No roles: returns [].
- Blank id: raises VoluntarioValidationError.
"""
from __future__ import annotations

import pytest

from app.modules.voluntarios.application.list_voluntario_roles import (
    VoluntarioValidationError,
    list_voluntario_roles,
)


class _FakeVoluntariosPort:
    __slots__ = ("_roles",)

    def __init__(self, roles: list[str]) -> None:
        self._roles = roles

    def list_voluntario_roles(self, voluntario_id: str) -> list[str]:
        return self._roles


class TestListVoluntarioRoles:
    def test_returns_sorted_roles(self) -> None:
        port = _FakeVoluntariosPort(["acogida", "intake", "salud"])
        assert list_voluntario_roles(port, "11111111-1111-1111-1111-111111111111") == ["acogida", "intake", "salud"]  # type: ignore[arg-type]

    def test_no_roles_returns_empty_list(self) -> None:
        port = _FakeVoluntariosPort([])
        assert list_voluntario_roles(port, "11111111-1111-1111-1111-111111111111") == []  # type: ignore[arg-type]


class TestListVoluntarioRolesValidation:
    @pytest.mark.parametrize("voluntario_id", ["", "   "])
    def test_blank_id_raises(self, voluntario_id: str) -> None:
        port = _FakeVoluntariosPort([])
        with pytest.raises(VoluntarioValidationError):
            list_voluntario_roles(port, voluntario_id)  # type: ignore[arg-type]

    def test_none_id_raises(self) -> None:
        port = _FakeVoluntariosPort([])
        with pytest.raises(VoluntarioValidationError):
            list_voluntario_roles(port, None)  # type: ignore[arg-type]
