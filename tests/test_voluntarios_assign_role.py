"""TDD tests: assign_voluntario_role use case (epic #420 VOL-02).

Covers:
- Happy path: assigns role, returns Voluntario.
- Duplicate role: adapter raises UniqueViolationError → propagates.
- Blank/invalid rol: VoluntarioValidationError.
- Non-existent voluntario: adapter raises → propagates.
"""
from __future__ import annotations

import pytest

from app.core.data_access import UniqueViolationError
from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
)


class _FakeVoluntariosPort:
    __slots__ = ("_error",)

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def assign_voluntario_role(
        self, voluntario_id: str, rol: str
    ) -> Voluntario:
        if self._error:
            raise self._error
        return Voluntario(
            id=voluntario_id,
            voluntario="Ana Garcia",
            activo=True,
        )


def _assign_role(port: object, voluntario_id: str, rol: str) -> Voluntario:
    from app.modules.voluntarios.application.assign_voluntario_role import (
        assign_voluntario_role as _assign,
    )

    return _assign(port, voluntario_id=voluntario_id, rol=rol)  # type: ignore[arg-type]


class TestAssignRoleHappyPath:
    def test_returns_voluntario(self) -> None:
        port = _FakeVoluntariosPort()
        result = _assign_role(port, "11111111-1111-1111-1111-111111111111", "intake")
        assert isinstance(result, Voluntario)

    def test_valid_rol_types_accepted(self) -> None:
        port = _FakeVoluntariosPort()
        for rol in ("intake", "seguimiento", "acogida", "salud"):
            result = _assign_role(port, "v-1", rol)
            assert result.voluntario == "Ana Garcia"


class TestAssignRoleValidation:
    def test_invalid_rol_raises(self) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError):
            _assign_role(port, "v-1", "admin")  # not a RolVoluntario member

    @pytest.mark.parametrize("voluntario_id", ["", "   "])
    def test_blank_id_raises(self, voluntario_id: str) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError):
            _assign_role(port, voluntario_id, "intake")

    def test_none_id_raises(self) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError):
            _assign_role(port, None, "intake")  # type: ignore[arg-type]


class TestAssignRoleAdapterErrors:
    def test_unique_violation_propagates(self) -> None:
        port = _FakeVoluntariosPort(
            error=UniqueViolationError("unique constraint violation")
        )
        with pytest.raises(UniqueViolationError):
            _assign_role(port, "v-1", "intake")

    def test_insforge_error_propagates(self) -> None:
        port = _FakeVoluntariosPort(error=RuntimeError("network"))
        with pytest.raises(RuntimeError):
            _assign_role(port, "v-1", "intake")
