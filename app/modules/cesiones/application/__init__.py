"""Application layer — Cesiones slice.

One file per use case. Each use case is a plain function that
orchestrates domain + port. No SQL, no LocalBackend, no HTTP.
"""

from __future__ import annotations

from app.modules.cesiones.application.create_cesion import create_cesion
from app.modules.cesiones.application.get_cesion_by_entrada_id import (
    get_cesion_by_entrada_id,
)
from app.modules.cesiones.application.list_cesiones import list_cesiones

__all__ = ["create_cesion", "get_cesion_by_entrada_id", "list_cesiones"]
