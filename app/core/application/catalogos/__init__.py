"""Use-case layer for the catalog (reference-data) tables.

Each ``list_<name>`` function is a thin orchestrator that delegates to
the :class:`CatalogosPort` interface. The use case does NOT do
validation, mapping, or I/O — those concerns live in the adapter
(see :mod:`app.core.adapters.local_backend`). The single-line delegation is
deliberate: it makes the orchestrator trivially testable (a single
``port.list_origenes()`` call, mocked at the port boundary) and keeps
the seam between "what the app wants to do" and "how the backend
serves it" explicit.

Hexagonal taxonomy:

- Domain    :mod:`app.core.catalogos` (pure dataclasses)
- Port      :mod:`app.core.ports.catalogos_port` (Protocol)
- THIS      :mod:`app.core.application.catalogos` (use cases)
- Adapter   :mod:`app.core.adapters.local_backend` (concrete impl)
- DI        :mod:`app.core.di.catalogos_di` (FastAPI wiring)
"""


from __future__ import annotations

from app.core.application.catalogos.list_motivos import list_motivos
from app.core.application.catalogos.list_origenes import list_origenes
from app.core.application.catalogos.list_periodicidad import list_periodicidad
from app.core.application.catalogos.list_pruebas import list_pruebas
from app.core.application.catalogos.list_tipos_contrato import list_tipos_contrato

__all__ = [
    "list_motivos",
    "list_origenes",
    "list_periodicidad",
    "list_pruebas",
    "list_tipos_contrato",
]
