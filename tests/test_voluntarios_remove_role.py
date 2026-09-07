"""TDD tests: remove_voluntario_role use case (epic #420 VOL-02).

Covers:
- Happy path: removes role, returns Voluntario.
- Role not assigned: adapter returns Voluntario (no-op, idempotent).
- Blank/invalid rol: VoluntarioValidationError.
- Non-existent voluntario: adapter raises → propagates.
"""
from __future__ import annotations

import pytest

from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
)


class _FakeVoluntariosPort:
    __slots__ = ("_result",)

    def __init__(
        self, result: Voluntario | None = None
    ) -> None:
        self._result = result

    def remove_voluntario_role(
        self, voluntario_id: str, rol: str
    ) -> Voluntario:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result or Voluntario(
            id=voluntario_id,
            voluntario="Ana Garcia",
            activo=True,
        )


def _remove_role(port: object, voluntario_id: str, rol: str) -> Voluntario:
    from app.modules.voluntarios.application.remove_voluntario_role import (
        remove_voluntario_role as _remove,
    )

    return _remove(port, voluntario_id=voluntario_id, rol=rol)  # type: ignore[arg-type]


class TestRemoveRoleHappyPath:
    def test_returns_voluntario(self) -> None:
        port = _FakeVoluntariosPort(
            Voluntario(id="v-1", voluntario="Ana Garcia", activo=True)
        )
        result = _remove_role(port, "v-1", "intake")
        assert isinstance(result, Voluntario)

    def test_valid_rol_types_accepted(self) -> None:
        port = _FakeVoluntariosPort(
            Voluntario(id="v-1", voluntario="Ana Garcia", activo=True)
        )
        for rol in ("intake", "seguimiento", "acogida", "salud"):
            result = _remove_role(port, "v-1", rol)
            assert result.voluntario == "Ana Garcia"


class TestRemoveRoleValidation:
    def test_invalid_rol_raises(self) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError):
            _remove_role(port, "v-1", "admin")

    @pytest.mark.parametrize("voluntario_id", ["", "   "])
    def test_blank_id_raises(self, voluntario_id: str) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError):
            _remove_role(port, voluntario_id, "intake")

    def test_none_id_raises(self) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError):
            _remove_role(port, None, "intake")  # type: ignore[arg-type]


class TestRemoveRoleAdapterErrors:
    def test_backend_error_propagates(self) -> None:
        port = _FakeVoluntariosPort(result=RuntimeError("network"))  # type: ignore[arg-type]
        with pytest.raises(RuntimeError):
            _remove_role(port, "v-1", "intake")
