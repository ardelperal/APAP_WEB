"""Concrete LocalBackend adapters that satisfy the application's ports.

This package is the ONLY place under ``app/core/`` that implements the
hexagonal ports against :mod:`app.core.local_backend` (rule §31: domain
depends on Protocol, never on a concrete client). Each submodule owns
one port:

- ``auth_local_backend_adapter`` — :class:`AuthUsersPort` reads/writes
  for ``usuarios_autorizados``.
- ``catalogos_local_backend_adapter`` — :class:`CatalogosPort` reads.
- ``oauth_local_backend_adapter`` — :class:`OAuthPort` for the Google
  OAuth login flow.
- ``schema_bootstrap_local_backend_adapter`` — :class:`SchemaBootstrapPort`
  DDL/seed writes.

The SQL-execution adapters are the seam for rule §22 (query
construction is its own seam): SQL strings and parameter shaping
live there, not in the application layer. Each SQL adapter:

1. Holds a :class:`SqlExecutor` injected by the DI layer.
2. Builds the SQL string and parameters per use case.
3. Maps the raw row dict to the frozen domain entity.

The :class:`LocalBackendOAuthAdapter` is a thinner wrapper: it does
NOT execute SQL. It composes the OAuth protocol primitives
(PKCE minting + LocalBackend HTTP round-trips) on top of an
:class:`LocalPostgresExecutor` injected by the DI layer.

The adapters do NOT catch ``BackendError`` — the generic
exception handler registered in ``app/main.py`` translates any
unhandled error into a non-leaking 502 at the FastAPI boundary
(§32.P4 contract preserved via the generic handler). A unit
test that mocks the ``SqlExecutor`` to raise ``BackendError`` will
see the exception propagate untouched until the handler runs.
"""


from __future__ import annotations

from app.core.adapters.local_backend.auth_local_backend_adapter import (
    LocalBackendAuthUsersAdapter,
)
from app.core.adapters.local_backend.catalogos_local_backend_adapter import (
    LocalBackendCatalogosAdapter,
)
from app.core.adapters.local_backend.oauth_local_backend_adapter import (
    LocalBackendOAuthAdapter,
)
from app.core.adapters.local_backend.schema_bootstrap_local_backend_adapter import (
    LocalBackendSchemaBootstrapAdapter,
)

__all__ = [
    "LocalBackendAuthUsersAdapter",
    "LocalBackendCatalogosAdapter",
    "LocalBackendOAuthAdapter",
    "LocalBackendSchemaBootstrapAdapter",
]
