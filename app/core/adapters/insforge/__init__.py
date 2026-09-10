"""Re-exports from LocalBackend adapters (see issues #728, #725).

All InsForge-era adapters in this directory have been migrated or deleted:
- ``auth_adapter`` → :class:`app.core.local_backend.auth_adapter.LocalBackendAuthUsersAdapter`
- ``catalogos_adapter`` → :class:`app.core.local_backend.catalogos_adapter.LocalBackendCatalogosAdapter`
- ``schema_bootstrap_adapter`` → :class:`app.core.local_backend.schema_bootstrap_adapter.LocalBackendSchemaBootstrapAdapter`
- ``oauth_adapter`` → :class:`app.core.local_backend.oauth_adapter.LocalBackendOAuthAdapter`
- ``BackendErrorTranslation`` → :class:`app.core.di.insforge_error_handler_di.BackendErrorTranslation`

This module is kept as a re-export shim for backward compatibility. Import
from the new paths directly in new code.
"""

from __future__ import annotations

from app.core.di.insforge_error_handler_di import (
    BackendErrorTranslation,
    InsForgeErrorTranslation,  # backward-compat alias
)
from app.core.local_backend.auth_adapter import (
    LocalBackendAuthUsersAdapter as InsForgeAuthUsersAdapter,
)
from app.core.local_backend.catalogos_adapter import (
    LocalBackendCatalogosAdapter as InsForgeCatalogosAdapter,
)
from app.core.local_backend.oauth_adapter import (
    LocalBackendOAuthAdapter as InsForgeOAuthAdapter,
)
from app.core.local_backend.schema_bootstrap_adapter import (
    LocalBackendSchemaBootstrapAdapter as InsForgeSchemaBootstrapAdapter,
)

__all__ = [
    "BackendErrorTranslation",
    "InsForgeAuthUsersAdapter",
    "InsForgeCatalogosAdapter",
    "InsForgeErrorTranslation",
    "InsForgeOAuthAdapter",
    "InsForgeSchemaBootstrapAdapter",
]
