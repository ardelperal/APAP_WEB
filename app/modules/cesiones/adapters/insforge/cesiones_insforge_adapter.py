"""InsForge adapter — implements ``CesionesPort`` via the existing service.

The existing ``service.py`` already owns SQL, validation and mapping.
This adapter wires it behind the port interface, keeping the service
as the single SQL/implementation file per HR-5.

HR-6: ``InsForgeClient`` and ``InsForgeError`` are confined here.
Module-level imports are deferred to runtime (``sys.modules`` lookup) so
that test monkeypatches (``monkeypatch.setattr(cesiones_service,
"create_cesion", ...)``) take effect even when the module was imported
before the patch was applied.
"""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).


from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from app.core.data_access import SqlExecutor

if TYPE_CHECKING:
    from app.modules.cesiones.domain.cesion import Cesion, Contrato


def _svc() -> Any:
    """Runtime service-module lookup so test monkeypatches apply.

    Using ``sys.modules`` ensures we always get the current state of
    ``app.modules.cesiones.service``, even if the module was imported
    before the test installed the patch.
    """
    return sys.modules["app.modules.cesiones.service"]


class CesionesInsforgeAdapter:
    """InsForge-backed adapter for ``CesionesPort``.

    Wraps the existing ``service.py`` use cases.
    The service uses ``SqlExecutor`` (no direct InsForge calls),
    so this adapter only wires the SqlExecutor dependency.
    """

    __slots__ = ("_client",)

    def __init__(self, client: SqlExecutor) -> None:
        self._client = client

    # -------------------------------------------------------------------------
    # CesionesPort implementation
    # -------------------------------------------------------------------------

    def create_cesion(self, params: dict[str, Any]) -> tuple[Cesion, Contrato]:
        return _svc().create_cesion(self._client, params)

    def get_cesion_by_entrada_id(self, entrada_id: str) -> Cesion | None:
        return _svc().get_cesion_by_entrada_id(self._client, entrada_id)

    def list_cesiones(self) -> list[Cesion]:
        return _svc().list_cesiones(self._client)
