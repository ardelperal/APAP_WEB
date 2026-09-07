"""Hexagonal port for the voluntarios slice (AGENTS.md §31).

PR-A of epic #420.  The port is the contract between the use cases
(``application/``) and the adapters (``adapters/stubs/`` — pending a real
``LocalPostgresExecutor``-backed adapter in the follow-up to #668).  No
FastAPI, no InsForge, no Jinja in this file.

Adapters MUST translate transport-level errors into the
Protocol-level exceptions declared in :mod:`app.core.data_access`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.voluntarios.domain.voluntario import Voluntario


@runtime_checkable
class VoluntariosPort(Protocol):
    """Backend-agnostic interface for the voluntarios slice."""

    def list_voluntarios(self) -> list[Voluntario]:
        """Return all active volunteers, ordered alphabetically by name."""

    def get_voluntario_by_id(self, voluntario_id: str) -> Voluntario | None:
        """Return the volunteer with this UUID, or ``None`` if not found."""

    def create_voluntario(  # noqa: N803, PLR0913
        self,
        *,
        nombre: str,
        tel1: str | None = None,
        tel2: str | None = None,
        email: str | None = None,
        dni: str | None = None,
    ) -> Voluntario:
        """Insert a new volunteer and return the persisted row."""

    def deactivate_voluntario(self, voluntario_id: str) -> bool:
        """Soft-delete (sets ``activo = False``). Idempotent."""

    def list_voluntario_roles(self, voluntario_id: str) -> list[str]:
        """Return the operational roles assigned to ``voluntario_id``.

        Returns ``[]`` when the volunteer has no roles assigned.
        """

    def assign_voluntario_role(
        self, voluntario_id: str, rol: str
    ) -> Voluntario:
        """Assign role ``rol`` to ``voluntario_id``.

        ``rol`` must be a member of :class:`RolVoluntario`.
        Raises :class:`app.core.data_access.UniqueViolationError` when
        the role is already assigned (UNIQUE constraint on
        ``(voluntario_id, tipo_rol)``).
        """

    def remove_voluntario_role(
        self, voluntario_id: str, rol: str
    ) -> Voluntario:
        """Remove role ``rol`` from ``voluntario_id``.

        Idempotent: if the role is not assigned, returns the volunteer
        without error.
        """


__all__ = ["VoluntariosPort"]
