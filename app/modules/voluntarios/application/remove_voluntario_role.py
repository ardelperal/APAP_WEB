"""Use case: remove a role from a volunteer (epic #420 VOL-02).

Validates that ``rol`` is a member of :class:`RolVoluntario` before
delegating to the port.  The port is idempotent: if the role is not
currently assigned, it returns the volunteer without error.
"""
from __future__ import annotations

from app.modules.voluntarios.domain import VALID_ROL_TYPES
from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
    _require_non_blank,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def remove_voluntario_role(
    port: VoluntariosPort,
    *,
    voluntario_id: str,
    rol: str,
) -> Voluntario:
    """Remove role ``rol`` from ``voluntario_id``.

    Idempotent: if the role is not currently assigned, returns the
    volunteer without error.
    """
    clean_id = _require_non_blank(voluntario_id, "voluntario_id")
    clean_rol = _require_non_blank(rol, "rol")

    if clean_rol not in VALID_ROL_TYPES:
        raise VoluntarioValidationError(
            f"'{clean_rol}' no es un rol valido. "
            f"Usar uno de: {', '.join(sorted(VALID_ROL_TYPES))}"
        )

    return port.remove_voluntario_role(clean_id, clean_rol)


__all__ = ["remove_voluntario_role", "VoluntarioValidationError"]
