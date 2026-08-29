"""TDD tests: list_voluntarios use case (epic #420 PR-A).

Covers:
- Happy path: returns list of Voluntario.
- Empty DB returns [].
"""
from __future__ import annotations

from app.modules.voluntarios.application.list_voluntarios import list_voluntarios
from app.modules.voluntarios.domain.voluntario import Voluntario


class _FakeVoluntariosPort:
    __slots__ = ("_rows",)

    def __init__(self, rows: list[Voluntario]) -> None:
        self._rows = rows

    def list_voluntarios(self) -> list[Voluntario]:
        return self._rows


class TestListVoluntariosHappyPath:
    def test_returns_list_of_voluntarios(self) -> None:
        port = _FakeVoluntariosPort(
            [
                Voluntario(id="1", voluntario="Ana Garcia", activo=True),
                Voluntario(id="2", voluntario="Bea Ruiz", activo=True),
            ]
        )
        result = list_voluntarios(port)  # type: ignore[arg-type]
        assert len(result) == 2
        assert result[0].voluntario == "Ana Garcia"
        assert result[1].voluntario == "Bea Ruiz"

    def test_empty_db_returns_empty_list(self) -> None:
        port = _FakeVoluntariosPort([])
        assert list_voluntarios(port) == []  # type: ignore[arg-type]
