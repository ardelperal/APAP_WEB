"""Use case: create a new volunteer.

Slice: app/modules/voluntarios (epic #420 PR-A).
Single application-layer entry point for hexagonal volunteer creation.
Delegates to :class:`~app.modules.voluntarios.ports.voluntarios_port.VoluntariosPort`
so the application code stays transport-agnostic (AGENTS.md §31).

Validation rules preserved from the retired legacy service layer:
- ``nombre`` is mandatory and must be non-blank.
- ``email`` must contain ``@`` when provided.
- ``email`` and ``dni`` uniqueness propagates as ``UniqueViolation``
  from the adapter, which the route handler translates to HTTP 409.
"""
from __future__ import annotations

from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
    _require_non_blank,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def create_voluntario(
    port: VoluntariosPort,
    *,
    nombre: str,
    tel1: str | None = None,
    tel2: str | None = None,
    email: str | None = None,
    dni: str | None = None,
) -> Voluntario:
    """Create a new volunteer and return the persisted row.

    Validates ``nombre`` and ``email`` before delegating to the port.
    The adapter is responsible for primary-key generation and for raising
    :class:`app.core.data_access.UniqueViolation` when email or dni
    already exists; this wrapper does no DB work.
    """
    clean_nombre = _require_non_blank(nombre, "Nombre")

    return port.create_voluntario(
        nombre=clean_nombre,
        tel1=tel1,
        tel2=tel2,
        email=email,
        dni=dni,
    )


__all__ = ["create_voluntario", "VoluntarioValidationError"]
