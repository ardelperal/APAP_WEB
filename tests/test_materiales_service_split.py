from __future__ import annotations

from app.modules.materiales import estancia_material_service
from app.modules.materiales import service as catalog_service


def test_junction_crud_is_owned_by_estancia_material_service() -> None:
    public_api = {
        "assign_material_to_estancia",
        "list_materials_for_estancia",
        "remove_material_from_estancia",
    }

    assert public_api <= set(estancia_material_service.__all__)
    assert public_api.isdisjoint(vars(catalog_service))
