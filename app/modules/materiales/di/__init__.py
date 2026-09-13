"""FastAPI ``Depends`` wiring for the materiales slice (issue #752, PR 4 of 5).

The :func:`get_materiales_port` provider is the seam between FastAPI
request handlers and the hexagonal
:class:`~app.modules.materiales.ports.materiales_port.MaterialesPort`
abstraction. Routes depend on ``MaterialesPort``; the concrete
:class:`~app.modules.materiales.adapters.local_backend.materiales_local_backend_adapter.LocalBackendMaterialesAdapter`
is hidden behind this dependency so the route layer does not import
any LocalBackend-shaped import (AGENTS.md §22, §31).

The provider delegates the request-scoped executor lookup to
:func:`app.core.di._yield_local_backend_port.yield_local_backend_port`
— the same helper used by ``catalogos_di``, ``oauth_di``, and
``schema_bootstrap_di`` — so the lifespan / fallback dance lives in
exactly one place.
"""

from app.modules.materiales.di.materiales_di import get_materiales_port

__all__ = ["get_materiales_port"]
