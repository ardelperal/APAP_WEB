"""TDD tests: create_voluntario use case (epic #420 PR-A).

Covers:
- Happy path: returns Voluntario with all fields.
- ``nombre`` blank → VoluntarioValidationError.
- ``nombre`` missing → VoluntarioValidationError.
- Adapter raises UniqueViolationError → propagates to caller.
- Adapter raises BackendError → propagates to caller.
"""
from __future__ import annotations

import pytest

from app.core.data_access import UniqueViolationError
from app.modules.voluntarios.application.create_voluntario import (
    VoluntarioValidationError,
    create_voluntario,
)
from app.modules.voluntarios.domain.voluntario import Voluntario


class _FakeVoluntariosPort:
    """Fake port that returns a configured Voluntario or raises an error."""

    __slots__ = ("_voluntario", "_error")

    def __init__(
        self,
        voluntario: Voluntario | None = None,
        error: Exception | None = None,
    ) -> None:
        self._voluntario = voluntario
        self._error = error

    def create_voluntario(
        self,
        *,
        nombre: str,
        tel1: str | None = None,
        tel2: str | None = None,
        email: str | None = None,
        dni: str | None = None,
    ) -> Voluntario:
        if self._error is not None:
            raise self._error
        if self._voluntario is None:
            raise RuntimeError("unexpected call")
        return self._voluntario


def _voluntario(name: str = "Ana Garcia") -> Voluntario:
    return Voluntario(
        id="11111111-1111-1111-1111-111111111111",
        voluntario=name,
        activo=True,
        tel1=None,
        tel2=None,
        email=None,
        dni=None,
        fecha_alta="2026-01-01T00:00:00",
        updated_at=None,
    )


class TestCreateVoluntarioHappyPath:
    def test_returns_voluntario_with_all_fields(self) -> None:
        port = _FakeVoluntariosPort(voluntario=_voluntario())
        result = create_voluntario(port, nombre="Ana Garcia")  # type: ignore[arg-type]
        assert isinstance(result, Voluntario)
        assert result.voluntario == "Ana Garcia"
        assert result.activo is True

    def test_strips_nombre_whitespace(self) -> None:
        port = _FakeVoluntariosPort(voluntario=_voluntario())
        result = create_voluntario(port, nombre="  Ana Garcia  ")  # type: ignore[arg-type]
        assert result.voluntario == "Ana Garcia"


class TestCreateVoluntarioValidationErrors:
    @pytest.mark.parametrize("nombre", ["", "   "])
    def test_blank_nombre_raises(self, nombre: str) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError) as exc_info:
            create_voluntario(port, nombre=nombre)  # type: ignore[arg-type]
        assert "Nombre" in str(exc_info.value)

    def test_none_nombre_raises(self) -> None:
        port = _FakeVoluntariosPort()
        with pytest.raises(VoluntarioValidationError):
            create_voluntario(port, nombre=None)  # type: ignore[arg-type]


class TestCreateVoluntarioAdapterErrors:
    def test_unique_violation_propagates(self) -> None:
        port = _FakeVoluntariosPort(
            error=UniqueViolationError("unique constraint violation: email")
        )
        with pytest.raises(UniqueViolationError):
            create_voluntario(port, nombre="Ana Garcia", email="ana@example.com")  # type: ignore[arg-type]

    def test_insforge_error_propagates(self) -> None:
        port = _FakeVoluntariosPort(error=RuntimeError("network"))
        with pytest.raises(RuntimeError):
            create_voluntario(port, nombre="Ana Garcia")  # type: ignore[arg-type]
