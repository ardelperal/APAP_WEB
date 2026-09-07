"""LocalBackend adapter family for the migration package.

Concrete adapters that implement the :mod:`migration.ports`
Protocols against the LocalBackend REST API. Each adapter takes the
backend-agnostic :class:`~app.core.data_access.SqlExecutor` (which
:class:`~app.core.local_backend.LocalPostgresExecutor` satisfies structurally)
so the use case layer never imports the LocalBackend client directly.
"""

from __future__ import annotations
