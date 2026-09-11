"""Domain entities for the materiales module (FOSTER-04, issue #46).

Pure dataclasses and exceptions — no I/O, no transport, no Protocol
imports. Moved here from ``app/modules/materiales/service.py`` as
the first step of the hexagonal refactor (issue #752, PR 1 of 5).
"""

from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.domain.exceptions import MaterialConflictError
from app.modules.materiales.domain.material import Material

__all__ = [
    "EstanciaMaterial",
    "Material",
    "MaterialConflictError",
]
