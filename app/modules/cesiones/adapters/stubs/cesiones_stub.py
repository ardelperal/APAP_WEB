"""Stub adapter for ``CesionesPort`` — pending local-backend implementation.

Replaces the deleted
:class:`app.modules.cesiones.adapters.insforge.cesiones_insforge_adapter.CesionesPort`.
A real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands in a follow-up slice; until then, every method raises
:class:`NotImplementedError` so the runtime fails loud per route.

See issue #6' for the follow-up that replaces this stub with a real
local-backend implementation.
"""

from __future__ import annotations

from app.modules.cesiones.ports.cesiones_port import CesionesPort


class StubCesionesPort(CesionesPort):
    """Placeholder :class:`CesionesPort` whose every method raises."""

    def create_cesion(self, *args, **kwargs):
        raise NotImplementedError(
            "CesionesPort.create_cesion: pending local-backend adapter, see #6'"
        )

    def get_cesion_by_entrada_id(self, *args, **kwargs):
        raise NotImplementedError(
            "CesionesPort.get_cesion_by_entrada_id: pending local-backend adapter, see #6'"
        )

    def list_cesiones(self, *args, **kwargs):
        raise NotImplementedError(
            "CesionesPort.list_cesiones: pending local-backend adapter, see #6'"
        )


__all__ = ["CesionesPort"]
