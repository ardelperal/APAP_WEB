"""Minimal intake entries module.

Public surface:

- ``service``: single-record CRUD for ``entradas`` (INTAKE-01, #87/#88/#89).
- ``routes``: HTTP layer for the single-record CRUD.
- ``batch_service``: staging + atomic commit for batch entradas
  (INTAKE-02, #40, Entradas Múltiples / legacy
  ``TbEntradasMultiplesAuxIniciales``).
- ``batch_routes``: HTTP layer for the batch flow.
"""

from app.modules.entradas.batch_routes import router as batch_router
from app.modules.entradas.batch_service import (
    BatchRecord,
    BatchStaging,
    BatchValidationError,
)
from app.modules.entradas.routes import router
from app.modules.entradas.service import Entrada, EntradaConflictError

__all__ = [
    "router",
    "batch_router",
    "Entrada",
    "EntradaConflictError",
    "BatchRecord",
    "BatchStaging",
    "BatchValidationError",
]
