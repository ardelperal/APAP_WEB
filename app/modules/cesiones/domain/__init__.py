"""Domain layer — Cesiones slice.

Contains only pure domain types: dataclasses and exception classes.
No I/O, no InsForge, no FastAPI, no SQL.
"""

from __future__ import annotations

from app.modules.cesiones.domain.cesion import Cesion, Contrato

__all__ = ["Cesion", "Contrato"]
