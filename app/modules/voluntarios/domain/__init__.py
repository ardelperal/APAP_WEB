"""Domain: voluntarios slice (AGENTS.md §31: domain has no I/O).

Exports the :class:`Voluntario` entity and the :class:`RolVoluntario` enum.
"""
from __future__ import annotations

from enum import StrEnum

from app.modules.voluntarios.domain.voluntario import Voluntario


class RolVoluntario(StrEnum):
    """Operational roles a volunteer can hold.

    The four members are closed: adding a new role means extending
    both this enum AND the CHECK constraint on ``roles_voluntario.tipo_rol``
    in the database schema (AGENTS.md §4 — the set is closed).
    """

    INTAKE = "intake"
    SEGUIMIENTO = "seguimiento"
    ACOGIDA = "acogida"
    SALUD = "salud"


#: Derived from the enum (AGENTS.md §4 — single source of truth per domain concept).
#: Do NOT hard-code; always derive from :class:`RolVoluntario`.
VALID_ROL_TYPES: frozenset[str] = frozenset(r.value for r in RolVoluntario)


__all__ = ["RolVoluntario", "VALID_ROL_TYPES", "Voluntario"]
