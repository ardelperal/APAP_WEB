"""Re-exports from the LocalBackend adapters (see issue #728).

The three SQL-execution adapters have been migrated to
``app/core/local_backend/``:

- ``auth_adapter`` → :class:`app.core.local_backend.auth_adapter.LocalBackendAuthUsersAdapter`
- ``catalogos_adapter`` → :class:`app.core.local_backend.catalogos_adapter.LocalBackendCatalogosAdapter`
- ``schema_bootstrap_adapter`` → :class:`app.core.local_backend.schema_bootstrap_adapter.LocalBackendSchemaBootstrapAdapter`

The OAuth and error-translation adapters (``oauth_insforge_adapter``,
``insforge_error_handler_insforge_adapter``) remain here pending the
Phase 3 rewrite (issue #725).

This module is kept as a re-export shim so callers that still import
from ``app.core.adapters.insforge`` continue to work during the migration
window. Import from the new path directly in new code.
"""

from __future__ import annotations

from app.core.adapters.insforge.insforge_error_handler_insforge_adapter import (
    InsForgeErrorTranslation,
)
from app.core.adapters.insforge.oauth_insforge_adapter import InsForgeOAuthAdapter
from app.core.local_backend.auth_adapter import (
    LocalBackendAuthUsersAdapter as InsForgeAuthUsersAdapter,
)
from app.core.local_backend.catalogos_adapter import (
    LocalBackendCatalogosAdapter as InsForgeCatalogosAdapter,
)
from app.core.local_backend.schema_bootstrap_adapter import (
    LocalBackendSchemaBootstrapAdapter as InsForgeSchemaBootstrapAdapter,
)

# Backwards-compatible re-exports (same names as before, new implementations)
__all__ = [
    "InsForgeAuthUsersAdapter",
    "InsForgeCatalogosAdapter",
    "InsForgeErrorTranslation",
    "InsForgeOAuthAdapter",
    "InsForgeSchemaBootstrapAdapter",
]
