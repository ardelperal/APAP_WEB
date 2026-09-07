"""InsForge adapter family for the migration package.

Concrete adapters that implement the :mod:`migration.ports`
Protocols against the InsForge REST API. Each adapter takes the
backend-agnostic :class:`~app.core.data_access.SqlExecutor` (which
:class:`~app.core.insforge.LocalPostgresExecutor` satisfies structurally)
so the use case layer never imports the InsForge client directly.
"""

from __future__ import annotations
