"""Use case: list active volunteers.

Slice: app/modules/voluntarios (epic #420 PR-A).
Delegates to :class:`~app.modules.voluntarios.ports.voluntarios_port.VoluntariosPort`.
"""
from __future__ import annotations

from app.modules.voluntarios.domain.voluntario import Voluntario
from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


def list_voluntarios(port: VoluntariosPort) -> list[Voluntario]:
    """Return all active volunteers, ordered alphabetically by name.

    Returns ``[]`` when no active volunteers exist.
    """
    return port.list_voluntarios()


__all__ = ["list_voluntarios"]
