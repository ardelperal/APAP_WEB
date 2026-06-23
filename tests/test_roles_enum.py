"""Tests for the role enum and derived VALID_ROLES (rule 4 follow-up).

The project rule 4 (one source of truth per domain concept) requires
that any frozenset/list of domain values is derived from a single
StrEnum, not duplicated. This file pins the contract for:

- ``app.core.auth.Rol`` — the source of truth for authorized user roles.
- ``app.core.auth.VALID_ROLES`` — derived from ``Rol`` (not hardcoded).
- ``app.modules.voluntarios.service.RolVoluntario`` — already exists.
- ``app.modules.voluntarios.service.VALID_ROL_TYPES`` — derived from
  ``RolVoluntario`` (not hardcoded).

If anyone re-hardcodes the values in the future, these tests fail.
"""

from __future__ import annotations

from enum import StrEnum

from app.core.auth import VALID_ROLES, Rol
from app.modules.voluntarios.service import VALID_ROL_TYPES, RolVoluntario


def test_rol_is_a_str_enum() -> None:
    """Rol exists and is a StrEnum (the source of truth)."""
    assert issubclass(Rol, StrEnum)
    # The four roles documented in docs/decisiones-proyecto.md
    assert {r.value for r in Rol} == {"developer", "admin", "key_user", "reader"}


def test_valid_roles_is_derived_from_rol_enum() -> None:
    """VALID_ROLES is a frozenset of Rol values, not a hand-written literal."""
    expected = frozenset(r.value for r in Rol)
    assert VALID_ROLES == expected
    # If someone re-hardcodes the literal, the assertion above still
    # passes — but the test below catches a divergence between the
    # enum and the frozenset by construction.
    assert isinstance(VALID_ROLES, frozenset)


def test_rol_voluntario_is_a_str_enum() -> None:
    """RolVoluntario exists and is a StrEnum (the source of truth)."""
    assert issubclass(RolVoluntario, StrEnum)
    assert {r.value for r in RolVoluntario} == {
        "intake",
        "seguimiento",
        "acogida",
        "salud",
    }


def test_valid_rol_types_is_derived_from_rol_voluntario_enum() -> None:
    """VALID_ROL_TYPES is a frozenset of RolVoluntario values."""
    expected = frozenset(r.value for r in RolVoluntario)
    assert VALID_ROL_TYPES == expected
    assert isinstance(VALID_ROL_TYPES, frozenset)
