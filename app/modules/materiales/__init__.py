"""FOSTER-04 materiales module (issue #752).

The legacy module re-exports were removed in PR 5 because they
introduced a circular import: the LocalBackend adapter imports
``app.modules.materiales.queries`` (to compose SQL), and the
queries submodule lives inside this package — any re-export at
the package root would force the adapter to load before the
package is fully initialised.

Callers that previously did ``from app.modules.materiales import
create_material, Material, materiales_router`` should now do one
of:

- ``from app.modules.materiales.application import create_material, Material``
- ``from app.modules.materiales.routes import router as materiales_router``
- ``from app.modules.materiales.acogida_routes import router as materiales_acogida_router``
- ``from app.modules.materiales.di import get_materiales_port``

The empty ``__init__`` is intentional; removing the legacy
re-exports is the only way to break the import cycle the
adapter <-> package root introduced when PR 5 lifted the row
mappers from ``service.py`` into the adapter.
"""
