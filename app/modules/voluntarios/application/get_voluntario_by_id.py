"""Use case: get a volunteer by UUID.

Slice: app/modules/voluntarios (epic #420 PR-A).
Delegates to :class:`~app.modules.voluntarios.ports.voluntarios_port.VoluntariosPort`.
"""
from __future__ import annotations

from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
    _require_non_blank,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def get_voluntario_by_id(
    port: VoluntariosPort,
    voluntario_id: str,
) -> Voluntario | None:
    """Return the volunteer with this UUID, or ``None`` if not found.

    ``voluntario_id`` is mandatory and non-blank (validated here).
    Returns both active and inactive records.
    """
    clean_id = _require_non_blank(voluntario_id, "voluntario_id")
    return port.get_voluntario_by_id(clean_id)


__all__ = ["get_voluntario_by_id", "VoluntarioValidationError"]
