"""Public port surface for the catalog (reference-data) tables.

The :class:`CatalogosPort` Protocol is the only thing the application
layer sees. New ports (e.g. ``VolunteersPort``) will live alongside
this module under ``app/core/ports/``.
"""


from __future__ import annotations

from app.core.ports.catalogos_port import CatalogosPort

__all__ = ["CatalogosPort"]
