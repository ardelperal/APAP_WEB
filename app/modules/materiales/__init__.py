"""FOSTER-04 materiales module — hexagonal (issue #752).

Exports the application-layer use cases + dataclasses + the two
routers (catalog + per-estancia junction) so the rest of the app
can do ``from app.modules.materiales import create_material,
Material, materiales_router, materiales_acogida_router``.

The hexagonal refactor (issue #752) replaced the legacy
``service.py`` and ``estancia_material_service.py`` modules with:

- ``application/`` — eight use cases that own validation policy
  and delegate to ``MaterialesPort``.
- ``adapters/local_backend/materiales_local_backend_adapter.py`` —
  the production ``MaterialesPort`` implementation against the
  LocalBackend executor.
- ``di/materiales_di.py`` — the FastAPI ``get_materiales_port``
  composition root.
- ``ports/materiales_port.py`` — the abstract ``MaterialesPort``
  Protocol.

This ``__init__.py`` re-exports the dataclasses and the use cases
so callers (routes, tests, future modules) reach them through a
single ``from app.modules.materiales import ...`` import.
"""

from app.modules.materiales import application
from app.modules.materiales.acogida_routes import router as materiales_acogida_router
from app.modules.materiales.application import (
    EstanciaMaterial,
    Material,
    MaterialConflictError,
    assign_material_to_estancia,
    create_material,
    deactivate_material,
    get_material_by_id,
    list_materials,
    list_materials_for_estancia,
    remove_material_from_estancia,
    update_material,
)
from app.modules.materiales.di import get_materiales_port
from app.modules.materiales.routes import router as materiales_router

__all__ = [
    "EstanciaMaterial",
    "Material",
    "MaterialConflictError",
    "application",
    "assign_material_to_estancia",
    "create_material",
    "deactivate_material",
    "get_material_by_id",
    "get_materiales_port",
    "list_materials",
    "list_materials_for_estancia",
    "materiales_acogida_router",
    "materiales_router",
    "remove_material_from_estancia",
    "update_material",
]
