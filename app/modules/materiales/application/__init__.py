"""Application layer for the materiales slice (FOSTER-04, issue #752, PR 3 of 5).

Hexagonal use cases own the validation policy the legacy ``service.py``
exported and translate the eight ``MaterialesPort`` methods into callable
business operations. Per AGENTS.md §31, every use case takes
``MaterialesPort`` (the Protocol) — never a transport client — so the
application code stays 100% free of SQL and of LocalBackend.

The use cases mirror the patterns in
:mod:`app.modules.animals.application` (one file per use case; the
``__all__`` export list is the public surface; ``AnimalValidationError``
analogue here is :class:`MaterialValidationError`).

Rules honoured:

- **§22 (SQL/service separation):** the use cases do not import
  ``queries`` or ``SqlExecutor``; SQL lives in the adapter.
- **§31 (domain depends on Protocol):** the use cases take the
  Protocol as their first argument; domain dataclasses and the
  conflict exception are the only inward imports.
- **§33 (test pin per slice):** every use case has at least one
  application-layer test in ``tests/test_materiales_application.py``.
"""

from app.modules.materiales.application.assign_material_to_estancia import (
    assign_material_to_estancia,
)
from app.modules.materiales.application.create_material import (
    MaterialValidationError,
    create_material,
)
from app.modules.materiales.application.deactivate_material import (
    deactivate_material,
)
from app.modules.materiales.application.get_material_by_id import (
    get_material_by_id,
)
from app.modules.materiales.application.list_materials import (
    list_materials,
)
from app.modules.materiales.application.list_materials_for_estancia import (
    list_materials_for_estancia,
)
from app.modules.materiales.application.remove_material_from_estancia import (
    remove_material_from_estancia,
)
from app.modules.materiales.application.update_material import (
    update_material,
)

__all__ = [
    "MaterialValidationError",
    "assign_material_to_estancia",
    "create_material",
    "deactivate_material",
    "get_material_by_id",
    "list_materials",
    "list_materials_for_estancia",
    "remove_material_from_estancia",
    "update_material",
]
