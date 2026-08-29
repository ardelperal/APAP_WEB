"""Use case: list a volunteer's operational roles.

Slice: app/modules/voluntarios (epic #420 PR-A).
Delegates to :class:`~app.modules.voluntarios.ports.voluntarios_port.VoluntariosPort`.
"""
from __future__ import annotations

from app.modules.voluntarios.domain.voluntario_validation import (
    VoluntarioValidationError,
    _require_non_blank,
)
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def list_voluntario_roles(
    port: VoluntariosPort,
    voluntario_id: str,
) -> list[str]:
    """Return the operational roles assigned to ``voluntario_id``.

    Returns ``[]`` when the volunteer has no roles or does not exist.
    ``voluntario_id`` is mandatory and non-blank (validated here).
    """
    clean_id = _require_non_blank(voluntario_id, "voluntario_id")
    return port.list_voluntario_roles(clean_id)


__all__ = ["list_voluntario_roles", "VoluntarioValidationError"]
