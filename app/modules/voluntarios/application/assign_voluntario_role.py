"""Use case: assign a role to a volunteer (epic #420 VOL-02).

Validates that ``rol`` is a member of :class:`RolVoluntario` before
delegating to the port.  :class:`UniqueViolationError` from the adapter
propagates to the caller so the route can translate it to HTTP 409.
"""
from __future__ import annotations

from app.modules.voluntarios.domain import VALID_ROL_TYPES
from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
    _require_non_blank,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def assign_voluntario_role(
    port: VoluntariosPort,
    *,
    voluntario_id: str,
    rol: str,
) -> Voluntario:
    """Assign role ``rol`` to ``voluntario_id``.

    Validates that ``rol`` is a member of :class:`RolVoluntario` before
    delegating to the port.
    """
    clean_id = _require_non_blank(voluntario_id, "voluntario_id")
    clean_rol = _require_non_blank(rol, "rol")

    if clean_rol not in VALID_ROL_TYPES:
        raise VoluntarioValidationError(
            f"'{clean_rol}' no es un rol valido. "
            f"Usar uno de: {', '.join(sorted(VALID_ROL_TYPES))}"
        )

    return port.assign_voluntario_role(clean_id, clean_rol)


__all__ = ["assign_voluntario_role", "VoluntarioValidationError"]
