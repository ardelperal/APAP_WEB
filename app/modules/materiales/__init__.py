"""FOSTER-04 materiales module — catalog + estancia assignment (Refs #46).

Exports the service + the two routers (catalog + per-estancia junction)
so the rest of the app can do ``from app.modules.materiales import
service, router, junction_router, Material, EstanciaMaterial,
MaterialConflictError``.

PR A of the FOSTER-04 chained-PR series delivers ONLY the service
skeleton + dataclasses + SQL constants + mapping helpers. The catalog
routes land in PR B; the per-estancia junction routes + templates +
detail-page integration land in PR C. See ``sdd/foster-04-materiales/tasks``
(engram obs #15905) for the full split.
"""

from app.modules.materiales import service
from app.modules.materiales.acogida_routes import router as materiales_acogida_router
from app.modules.materiales.routes import router as materiales_router
from app.modules.materiales.service import (
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

__all__ = [
    "service",
    "materiales_router",
    "materiales_acogida_router",
    "Material",
    "EstanciaMaterial",
    "MaterialConflictError",
    "create_material",
    "get_material_by_id",
    "list_materials",
    "update_material",
    "deactivate_material",
    "assign_material_to_estancia",
    "list_materials_for_estancia",
    "remove_material_from_estancia",
]
