"""Use case: soft-delete a volunteer.

Slice: app/modules/voluntarios (epic #420 PR-A).
Delegates to :class:`~app.modules.voluntarios.ports.voluntarios_port.VoluntariosPort`.
"""
from __future__ import annotations

from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
    _require_non_blank,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def deactivate_voluntario(
    port: VoluntariosPort,
    voluntario_id: str,
) -> bool:
    """Soft-delete ``voluntario_id`` (sets ``activo = False``).

    Idempotent: returns ``False`` when the volunteer is already
    inactive.  Returns ``True`` on a successful deactivation.

    ``voluntario_id`` is mandatory and non-blank (validated here).
    """
    clean_id = _require_non_blank(voluntario_id, "voluntario_id")
    return port.deactivate_voluntario(clean_id)


__all__ = ["deactivate_voluntario", "VoluntarioValidationError"]
