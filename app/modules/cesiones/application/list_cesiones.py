"""Use case: list all owner-surrender records.

Slice: app/modules/cesiones (hexagonal migration).
Delegates to :class:`~app.modules.cesiones.ports.cesiones_port.CesionesPort`.
"""

from __future__ import annotations

from app.modules.cesiones.domain.cesion import Cesion
from app.modules.cesiones.ports.cesiones_port import CesionesPort


def list_cesiones(port: CesionesPort) -> list[Cesion]:
    """Return all cesiones, newest first."""
    return port.list_cesiones()


__all__ = ["list_cesiones"]
