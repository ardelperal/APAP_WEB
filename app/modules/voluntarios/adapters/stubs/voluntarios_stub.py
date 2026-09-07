"""Stub adapter for ``VoluntariosPort`` — pending local-backend implementation.

Replaces the deleted
:class:`app.modules.voluntarios.adapters.local_backend.voluntarios_local_backend_adapter.VoluntariosLocalBackendAdapter`
and its 3 sibling modules under ``app.modules.voluntarios.adapters.local_backend.*``.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

Affected routes (return 500 until the real adapter lands):

- ``GET /voluntarios`` (list_voluntarios)
- ``GET /voluntarios/<id>`` (get_voluntario_by_id)
- ``POST /voluntarios`` (create_voluntario)
- ``POST /voluntarios/<id>/deactivate`` (deactivate_voluntario)
- ``GET /voluntarios/<id>/roles`` (list_voluntario_roles)
- ``POST /voluntarios/<id>/roles`` (assign_voluntario_role)
- ``DELETE /voluntarios/<id>/roles/<role>`` (remove_voluntario_role)

See issue #6' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.modules.voluntarios.ports.voluntarios_port import VoluntariosPort


class StubVoluntariosPort(VoluntariosPort):
    """Placeholder :class:`VoluntariosPort` whose every method raises."""

    def list_voluntarios(self, *args, **kwargs):
        raise NotImplementedError(
            "VoluntariosPort.list_voluntarios: pending local-backend adapter, see #6'"
        )

    def get_voluntario_by_id(self, *args, **kwargs):
        raise NotImplementedError(
            "VoluntariosPort.get_voluntario_by_id: pending local-backend adapter, see #6'"
        )

    def create_voluntario(self, *args, **kwargs):
        raise NotImplementedError(
            "VoluntariosPort.create_voluntario: pending local-backend adapter, see #6'"
        )

    def deactivate_voluntario(self, *args, **kwargs):
        raise NotImplementedError(
            "VoluntariosPort.deactivate_voluntario: pending local-backend adapter, see #6'"
        )

    def list_voluntario_roles(self, *args, **kwargs):
        raise NotImplementedError(
            "VoluntariosPort.list_voluntario_roles: pending local-backend adapter, see #6'"
        )

    def assign_voluntario_role(self, *args, **kwargs):
        raise NotImplementedError(
            "VoluntariosPort.assign_voluntario_role: pending local-backend adapter, see #6'"
        )

    def remove_voluntario_role(self, *args, **kwargs):
        raise NotImplementedError(
            "VoluntariosPort.remove_voluntario_role: pending local-backend adapter, see #6'"
        )


__all__ = ["StubVoluntariosPort"]
