"""Contracts slice: DOC-01 (#56) — hexagonal port surface.

The ports in this package are the contracts the slice exposes to other
layers. Domain entities and use cases depend on these Protocol surfaces;
the concrete transport (weasyprint for PDF generation, MinIO for object
storage) lives under ``app/modules/contratos/adapters/local_backend/``
and is the only layer allowed to import transport modules.

The split mirrors :mod:`:`app.modules.animals.ports` (rule §31: domain
services depend on Protocol abstractions, never on concrete transport).
"""

from __future__ import annotations

__all__: list[str] = []
